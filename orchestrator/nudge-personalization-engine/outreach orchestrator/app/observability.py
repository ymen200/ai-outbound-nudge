"""
Observability Aggregator — collects and merges metrics from both modules.

Provides a unified view of token usage, prompt history, quality scores,
and system health across the entire outreach pipeline.
"""

import logging
from typing import Dict, Any, List, Optional
from .clients import SequenceGeneratorClient, MessageGeneratorClient

logger = logging.getLogger(__name__)

# Cached snapshot for fast MCP responses
_cached_snapshot: Optional[Dict[str, Any]] = None


class ObservabilityAggregator:
    """Aggregates observability data from Sequence Generator and Message Generator."""

    def __init__(
        self,
        seq_client: SequenceGeneratorClient = None,
        msg_client: MessageGeneratorClient = None,
    ):
        self.seq_client = seq_client or SequenceGeneratorClient()
        self.msg_client = msg_client or MessageGeneratorClient()

    async def collect_full_snapshot(self) -> Dict[str, Any]:
        """Fetch observability from both modules and merge into a unified snapshot."""
        global _cached_snapshot

        seq_obs = {}
        msg_obs = {}
        errors = []

        try:
            seq_obs = await self.seq_client.get_observability()
        except Exception as e:
            errors.append(f"sequence_generator_unreachable: {str(e)}")
            logger.warning(f"Sequence Generator observability failed: {e}")

        try:
            msg_obs = await self.msg_client.get_observability()
        except Exception as e:
            errors.append(f"message_generator_unreachable: {str(e)}")
            logger.warning(f"Message Generator observability failed: {e}")

        # Compute combined metrics
        seq_tokens = seq_obs.get("total_tokens", 0)
        msg_tokens = msg_obs.get("total_tokens", 0)
        seq_calls = seq_obs.get("total_gemini_calls", 0)
        msg_calls = msg_obs.get("total_llm_calls", 0)

        snapshot = {
            "sequence_generator": seq_obs,
            "message_generator": msg_obs,
            "combined": {
                "total_tokens": seq_tokens + msg_tokens,
                "total_tokens_in": seq_obs.get("total_tokens_in", 0) + msg_obs.get("total_tokens_in", 0),
                "total_tokens_out": seq_obs.get("total_tokens_out", 0) + msg_obs.get("total_tokens_out", 0),
                "total_llm_calls": seq_calls + msg_calls,
                "total_gemini_calls": seq_calls,
                "total_message_llm_calls": msg_calls,
            },
            "errors": errors,
        }

        _cached_snapshot = snapshot
        return snapshot

    def get_cached_snapshot(self) -> Dict[str, Any]:
        """Return the last collected snapshot (fast, no network calls)."""
        global _cached_snapshot
        if _cached_snapshot is None:
            return {"error": "No snapshot collected yet. Call collect_full_snapshot first."}
        return _cached_snapshot

    async def get_prompt_history(
        self,
        module: Optional[str] = None,
        agent_step: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Fetch prompt history from one or both modules, merged and sorted by timestamp."""
        records = []

        if module is None or module == "sequence_generator":
            try:
                seq_prompts = await self.seq_client.get_prompts(limit=limit, agent_step=agent_step)
                records.extend(seq_prompts)
            except Exception as e:
                logger.warning(f"Seq Gen prompt fetch failed: {e}")

        if module is None or module == "message_generator":
            try:
                msg_prompts = await self.msg_client.get_prompts(limit=limit, agent_step=agent_step)
                records.extend(msg_prompts)
            except Exception as e:
                logger.warning(f"Msg Gen prompt fetch failed: {e}")

        # Sort by timestamp (newest first)
        records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
        return records[:limit]

    async def override_config(self, module: str, overrides: Dict[str, Any]) -> Dict[str, Any]:
        """Push config overrides to a specific module."""
        if module == "sequence_generator":
            return await self.seq_client.override_config(overrides)
        elif module == "message_generator":
            return await self.msg_client.override_config(overrides)
        else:
            return {"error": f"Unknown module: {module}. Use 'sequence_generator' or 'message_generator'."}

    async def inject_feedback(self, module: str, feedback: str, lead_id: Optional[str] = None) -> Dict[str, Any]:
        """Inject feedback to a specific module.
        
        If lead_id is provided, feedback is scoped to that lead only (sequence_generator).
        """
        if module == "sequence_generator":
            return await self.seq_client.inject_feedback(feedback, lead_id=lead_id)
        elif module == "message_generator":
            return await self.msg_client.inject_feedback(feedback)
        else:
            return {"error": f"Unknown module: {module}. Use 'sequence_generator' or 'message_generator'."}

    async def reset_config(self, module: str) -> Dict[str, Any]:
        """Reset config overrides on a specific module."""
        if module == "sequence_generator":
            return await self.seq_client.reset_config()
        elif module == "message_generator":
            return await self.msg_client.reset_config()
        else:
            return {"error": f"Unknown module: {module}. Use 'sequence_generator' or 'message_generator'."}

    async def check_health(self) -> Dict[str, Any]:
        """Check health of both modules."""
        result = {}
        try:
            result["sequence_generator"] = await self.seq_client.health()
        except Exception as e:
            result["sequence_generator"] = {"status": "unreachable", "error": str(e)}
        try:
            result["message_generator"] = await self.msg_client.health()
        except Exception as e:
            result["message_generator"] = {"status": "unreachable", "error": str(e)}
        return result
