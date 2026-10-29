"""
Async REST clients for the downstream modules (Sequence Generator and Message Generator).

The Outreach Orchestrator uses these to call module APIs and collect observability data.

Resilience features:
- Exponential backoff WITH jitter to prevent thundering-herd
- Retry only on retryable errors (5xx, timeouts, connection errors) — NOT 4xx
- Explicit connect/read/write timeout separation
- Idempotency keys for non-idempotent POST endpoints
- Uniform error parsing
"""

import asyncio
import httpx
import logging
import uuid
from typing import Dict, Any, List, Optional
from tenacity import (
    retry,
    stop_after_attempt,
    stop_after_delay,
    stop_any,
    wait_exponential_jitter,
    retry_if_exception_type,
    retry_if_exception,
    before_sleep_log,
)
from .config import settings

logger = logging.getLogger(__name__)

# Maximum total time for all retry attempts combined (hard ceiling for starting new attempts)
# Prevents caller from hanging indefinitely on retries.
#
# NOTE: stop_after_delay prevents NEW attempts from starting after this time,
# but does NOT abort an attempt already in progress. With a 120s read timeout,
# worst case is ~300s (180s + one full in-flight attempt). This is acceptable
# for LLM-heavy endpoints where we don't want to cancel mid-generation.
# If stricter deadlines are needed, reduce _HEAVY_TIMEOUT read value.
MAX_TOTAL_RETRY_SECONDS = 180  # 3 minutes


# ---------------------------------------------------------------------------
# Retry predicates
# ---------------------------------------------------------------------------

def _is_retryable_status(exc: httpx.HTTPStatusError) -> bool:
    """Only retry on server errors (5xx) and specific transient statuses."""
    return exc.response.status_code in (500, 502, 503, 504, 408, 429)


def _is_retryable(exc: BaseException) -> bool:
    """Return True if the exception is retryable."""
    if isinstance(exc, httpx.ConnectTimeout):
        return True
    if isinstance(exc, httpx.ReadTimeout):
        return True
    if isinstance(exc, httpx.WriteTimeout):
        return True
    if isinstance(exc, httpx.PoolTimeout):
        return True
    if isinstance(exc, httpx.ConnectError):
        return True
    if isinstance(exc, httpx.ReadError):
        return True
    if isinstance(exc, httpx.WriteError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return _is_retryable_status(exc)
    return False


# ---------------------------------------------------------------------------
# Timeout configuration
# ---------------------------------------------------------------------------

# Short connect timeout, longer read/write for LLM-heavy endpoints
_FAST_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=10.0,
    write=5.0,
    pool=5.0,
)

_HEAVY_TIMEOUT = httpx.Timeout(
    connect=5.0,
    read=120.0,  # LLM calls can take a while
    write=10.0,
    pool=5.0,
)


# ---------------------------------------------------------------------------
# Uniform error parsing
# ---------------------------------------------------------------------------

def _parse_error_response(resp: httpx.Response) -> Dict[str, Any]:
    """
    Parse error response into a uniform format.

    Handles both:
    - {"detail": "..."} (FastAPI HTTPException)
    - {"success": false, "error": "..."} (application-level errors)
    """
    try:
        body = resp.json()
    except Exception:
        return {"code": resp.status_code, "message": resp.text[:500]}

    # FastAPI HTTPException format
    if "detail" in body:
        return {"code": resp.status_code, "message": body["detail"]}

    # Application-level error format
    if "error" in body:
        return {"code": resp.status_code, "message": body["error"]}

    # Unknown format
    return {"code": resp.status_code, "message": str(body)[:500]}


class OrchestratorClientError(Exception):
    """Raised when a downstream module returns an error."""

    def __init__(self, status_code: int, message: str, endpoint: str):
        self.status_code = status_code
        self.message = message
        self.endpoint = endpoint
        super().__init__(f"[{status_code}] {endpoint}: {message}")


# ---------------------------------------------------------------------------
# Base client with shared retry logic
# ---------------------------------------------------------------------------

class _BaseClient:
    """Base class with shared retry configuration."""

    def __init__(self, base_url: str, timeout: httpx.Timeout):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _get_retry_config(self, operation_name: str):
        """
        Return tenacity retry decorator with jitter and proper predicates.

        Uses:
        - wait_exponential_jitter: Exponential backoff WITH random jitter
          (initial * 2^n + random(0, jitter)) to prevent thundering-herd
        - stop_any: Stops after 3 attempts OR after MAX_TOTAL_RETRY_SECONDS total
        """
        return retry(
            stop=stop_any(
                stop_after_attempt(3),
                stop_after_delay(MAX_TOTAL_RETRY_SECONDS),
            ),
            wait=wait_exponential_jitter(
                initial=1,   # Start at 1s
                max=30,      # Cap at 30s
                exp_base=2,  # 1s, 2s, 4s, 8s, 16s, 30s
                jitter=2,    # Add 0-2s random jitter
            ),
            retry=retry_if_exception(_is_retryable),
            before_sleep=before_sleep_log(logger, logging.WARNING),
            reraise=True,
        )


# ---------------------------------------------------------------------------
# Sequence Generator Client
# ---------------------------------------------------------------------------

class SequenceGeneratorClient(_BaseClient):
    """Async REST client for the Sequence Generator (port 8001)."""

    def __init__(self, base_url: str = None):
        super().__init__(
            base_url=base_url or settings.SEQUENCE_GENERATOR_URL,
            timeout=_HEAVY_TIMEOUT,
        )

    async def generate_sequence(
        self,
        request: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /api/generate/sequence — full sequence generation pipeline.

        Args:
            request: The sequence generation request payload.
            idempotency_key: Optional key to prevent duplicate sequences on retry.
                            If not provided, one is generated automatically.

        Returns:
            The sequence generation response.

        Raises:
            OrchestratorClientError: If the request fails after retries.
        """
        url = f"{self.base_url}/api/generate/sequence"
        headers = {}

        # Add idempotency key if not provided
        if idempotency_key is None:
            idempotency_key = str(uuid.uuid4())
        headers["Idempotency-Key"] = idempotency_key

        @self._get_retry_config("generate_sequence")
        async def _do_request():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=request, headers=headers)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def approve_sequence(
        self,
        thread_id: str,
        approved: bool,
        feedback: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /api/approve/{thread_id} — approve or reject a paused sequence.

        Forwards to the Sequence Generator's approve endpoint, which resumes
        the graph from the dispatch_to_temporal interrupt.

        Args:
            thread_id: The thread ID from the sequence generation response.
            approved: True to approve and dispatch, False to reject with feedback.
            feedback: Optional feedback for regeneration (used when approved=False).

        Returns:
            The approval/dispatch response from the Sequence Generator.

        Raises:
            OrchestratorClientError: If the request fails after retries.
        """
        url = f"{self.base_url}/api/approve/{thread_id}"
        payload: Dict[str, Any] = {"approved": approved}
        if feedback:
            payload["user_feedback"] = feedback

        @self._get_retry_config("approve_sequence")
        async def _do_request():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def health(self) -> Dict[str, Any]:
        """GET /health — check if service is up."""
        url = f"{self.base_url}/health"

        @self._get_retry_config("health")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def get_observability(self) -> Dict[str, Any]:
        """GET /api/observability — token counts, call stats, model info."""
        url = f"{self.base_url}/api/observability"

        @self._get_retry_config("get_observability")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def get_prompts(self, limit: int = 50, agent_step: Optional[str] = None) -> List[Dict]:
        """GET /api/observability/prompts — actual prompts sent to Gemini."""
        url = f"{self.base_url}/api/observability/prompts"
        params = {"limit": limit}
        if agent_step:
            params["agent_step"] = agent_step

        @self._get_retry_config("get_prompts")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.get(url, params=params)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def override_config(self, overrides: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/config/override — change runtime settings."""
        url = f"{self.base_url}/api/config/override"

        @self._get_retry_config("override_config")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.post(url, json={"overrides": overrides})
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def reset_config(self) -> Dict[str, Any]:
        """POST /api/config/reset — clear all overrides."""
        url = f"{self.base_url}/api/config/reset"

        @self._get_retry_config("reset_config")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.post(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def inject_feedback(self, feedback: str, lead_id: Optional[str] = None) -> Dict[str, Any]:
        """POST /api/feedback — inject feedback for next generation.
        
        If lead_id is provided, feedback is scoped to that lead only.
        """
        url = f"{self.base_url}/api/feedback"
        payload: Dict[str, Any] = {"feedback": feedback}
        if lead_id:
            payload["lead_id"] = lead_id

        @self._get_retry_config("inject_feedback")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def clear_prompts(self) -> Dict[str, Any]:
        """POST /api/observability/clear — clear prompt history."""
        url = f"{self.base_url}/api/observability/clear"

        @self._get_retry_config("clear_prompts")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.post(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def flush_memory(self) -> Dict[str, Any]:
        """POST /api/memory/flush — flush both modules' memory."""
        url = f"{self.base_url}/api/memory/flush"

        @self._get_retry_config("flush_memory")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.post(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def get_paused_threads(self) -> Dict[str, Any]:
        """GET /api/paused-threads — list threads paused at dispatch_to_temporal."""
        url = f"{self.base_url}/api/paused-threads"

        @self._get_retry_config("get_paused_threads")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()


# ---------------------------------------------------------------------------
# Message Generator Client
# ---------------------------------------------------------------------------

class MessageGeneratorClient(_BaseClient):
    """Async REST client for the Message Generator (port 8000)."""

    def __init__(self, base_url: str = None):
        super().__init__(
            base_url=base_url or settings.MESSAGE_GENERATOR_URL,
            timeout=_HEAVY_TIMEOUT,
        )

    async def generate_message(
        self,
        request: Dict[str, Any],
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        POST /api/generate/simple — generate a single outreach message.

        Args:
            request: The message generation request payload.
            idempotency_key: Optional key to prevent duplicate messages on retry.

        Returns:
            The message generation response.

        Raises:
            OrchestratorClientError: If the request fails after retries.
        """
        url = f"{self.base_url}/api/generate/simple"
        headers = {}

        if idempotency_key is None:
            idempotency_key = str(uuid.uuid4())
        headers["Idempotency-Key"] = idempotency_key

        @self._get_retry_config("generate_message")
        async def _do_request():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(url, json=request, headers=headers)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def health(self) -> Dict[str, Any]:
        """GET / — check if service is up."""
        url = f"{self.base_url}/"

        @self._get_retry_config("health")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def get_observability(self) -> Dict[str, Any]:
        """GET /api/observability — token counts, call stats, quality scores."""
        url = f"{self.base_url}/api/observability"

        @self._get_retry_config("get_observability")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def get_prompts(self, limit: int = 50, agent_step: Optional[str] = None) -> List[Dict]:
        """GET /api/observability/prompts — actual prompts sent to LLM."""
        url = f"{self.base_url}/api/observability/prompts"
        params = {"limit": limit}
        if agent_step:
            params["agent_step"] = agent_step

        @self._get_retry_config("get_prompts")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.get(url, params=params)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def override_config(self, overrides: Dict[str, Any]) -> Dict[str, Any]:
        """POST /api/config/override — change runtime settings."""
        url = f"{self.base_url}/api/config/override"

        @self._get_retry_config("override_config")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.post(url, json={"overrides": overrides})
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def reset_config(self) -> Dict[str, Any]:
        """POST /api/config/reset — clear all overrides."""
        url = f"{self.base_url}/api/config/reset"

        @self._get_retry_config("reset_config")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.post(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def inject_feedback(self, feedback: str) -> Dict[str, Any]:
        """POST /api/feedback — inject feedback for next generation."""
        url = f"{self.base_url}/api/feedback"

        @self._get_retry_config("inject_feedback")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.post(url, json={"feedback": feedback})
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def clear_prompts(self) -> Dict[str, Any]:
        """POST /api/observability/clear — clear prompt history."""
        url = f"{self.base_url}/api/observability/clear"

        @self._get_retry_config("clear_prompts")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.post(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def get_memory_status(self) -> Dict[str, Any]:
        """GET /api/memory/status — check memory store status."""
        url = f"{self.base_url}/api/memory/status"

        @self._get_retry_config("get_memory_status")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

    async def flush_memory(self) -> Dict[str, Any]:
        """POST /api/memory/flush — wipe message generator memory."""
        url = f"{self.base_url}/api/memory/flush"

        @self._get_retry_config("flush_memory")
        async def _do_request():
            async with httpx.AsyncClient(timeout=_FAST_TIMEOUT) as client:
                resp = await client.post(url)
                if resp.status_code >= 400:
                    error = _parse_error_response(resp)
                    raise OrchestratorClientError(
                        status_code=resp.status_code,
                        message=error["message"],
                        endpoint=url,
                    )
                return resp.json()

        return await _do_request()

