"""
Observability infrastructure for the Message Generator.

Provides:
- PromptRecord: dataclass capturing every LLM call (prompt, response, tokens, latency)
- PromptStore: thread-safe in-memory history (capped, FIFO eviction, Redis-ready)
- RuntimeConfig: mutable overlay on top of immutable Settings for global orchestrator overrides
"""

import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


# ---------------------------------------------------------------------------
# PromptRecord — one record per LLM call
# ---------------------------------------------------------------------------

@dataclass
class PromptRecord:
    timestamp: str              # ISO-8601 UTC
    module: str                 # "message_generator"
    agent_step: str             # "planner", "researcher", "strategist", "writer", "critic"
    prompt: str                 # full prompt sent to LLM
    system_instruction: Optional[str] = None
    response: Optional[str] = None
    tokens_in: int = 0          # actual input tokens from provider usage_metadata
    tokens_out: int = 0         # actual output tokens from provider usage_metadata
    model_used: str = "primary" # "primary" or "fallback"
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# PromptStore — capped in-memory history, thread-safe
# ---------------------------------------------------------------------------

class PromptStore:
    """Thread-safe in-memory prompt history with FIFO eviction.
    
    Swap internals to Redis when persistence is needed — the public API
    stays the same.
    """

    MAX_RECORDS = 1000  # Cap to prevent unbounded growth

    def __init__(self, module: str = "message_generator"):
        self._module = module
        self._records: List[PromptRecord] = []
        self._lock = threading.Lock()

    def record(self, rec: PromptRecord) -> None:
        """Append a PromptRecord, evicting oldest if at capacity."""
        rec.module = self._module
        with self._lock:
            if len(self._records) >= self.MAX_RECORDS:
                self._records.pop(0)  # FIFO eviction
            self._records.append(rec)

    def get_history(
        self,
        limit: int = 50,
        agent_step: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return recent records (newest first), optionally filtered by agent_step."""
        with self._lock:
            records = list(reversed(self._records))
        if agent_step:
            records = [r for r in records if r.agent_step == agent_step]
        return [r.to_dict() for r in records[:limit]]

    def get_summary(self) -> Dict[str, Any]:
        """Aggregate summary statistics."""
        with self._lock:
            records = list(self._records)

        if not records:
            return {
                "total_calls": 0,
                "total_tokens_in": 0,
                "total_tokens_out": 0,
                "total_tokens": 0,
                "avg_latency_ms": 0.0,
                "calls_by_agent": {},
                "success_rate": 0.0,
            }

        calls_by_agent: Dict[str, int] = {}
        total_in = 0
        total_out = 0
        total_latency = 0.0
        successes = 0

        for r in records:
            calls_by_agent[r.agent_step] = calls_by_agent.get(r.agent_step, 0) + 1
            total_in += r.tokens_in
            total_out += r.tokens_out
            total_latency += r.latency_ms
            if r.success:
                successes += 1

        return {
            "total_calls": len(records),
            "total_tokens_in": total_in,
            "total_tokens_out": total_out,
            "total_tokens": total_in + total_out,
            "avg_latency_ms": round(total_latency / len(records), 2),
            "calls_by_agent": calls_by_agent,
            "success_rate": round(successes / len(records) * 100, 1),
        }

    def clear(self) -> int:
        """Clear all records. Returns count deleted."""
        with self._lock:
            count = len(self._records)
            self._records.clear()
        return count


# ---------------------------------------------------------------------------
# RuntimeConfig — mutable overlay on top of immutable Settings
# ---------------------------------------------------------------------------

# Whitelist of settings the global orchestrator is allowed to override
ALLOWED_OVERRIDE_KEYS = {
    "GEMINI_TEMPERATURE",
    "GEMINI_MAX_TOKENS",
    "MAX_ITERATIONS",
    "MIN_QUALITY_SCORE",
    "LOG_LEVEL",
    "ENABLE_HUMAN_REVIEW",
    "ENABLE_AUTO_SEND",
    "ENABLE_LEARNING_LOOP",
    "DEBUG_MODE",
}


class RuntimeConfig:
    """Mutable overlay on top of immutable pydantic BaseSettings.

    The global orchestrator can override whitelisted keys at runtime.
    Original settings remain untouched — call reset() to revert.
    """

    def __init__(self, settings_obj):
        self._settings = settings_obj
        self._overrides: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a config value — override takes precedence, then original settings."""
        with self._lock:
            if key in self._overrides:
                return self._overrides[key]
        return getattr(self._settings, key, default)

    def set(self, key: str, value: Any) -> bool:
        """Override a config value. Returns False if key is not whitelisted."""
        if key not in ALLOWED_OVERRIDE_KEYS:
            return False
        with self._lock:
            self._overrides[key] = value
        return True

    def reset(self, key: Optional[str] = None) -> None:
        """Reset override(s). Pass key to reset one, None to reset all."""
        with self._lock:
            if key:
                self._overrides.pop(key, None)
            else:
                self._overrides.clear()

    def get_all_overrides(self) -> Dict[str, Any]:
        """Return current overrides."""
        with self._lock:
            return dict(self._overrides)


# ---------------------------------------------------------------------------
# Module-level singleton instances
# ---------------------------------------------------------------------------

prompt_store = PromptStore(module="message_generator")

# Pending feedback from global orchestrator — consumed by next writer/critic call
pending_feedback: List[str] = []

# RuntimeConfig is initialized in main.py after settings is imported
runtime_config: Optional[RuntimeConfig] = None


def init_runtime_config(settings_obj):
    """Initialize the global runtime_config singleton."""
    global runtime_config
    runtime_config = RuntimeConfig(settings_obj)
    return runtime_config


def get_runtime_config() -> RuntimeConfig:
    """Get the runtime config, initializing with defaults if needed."""
    global runtime_config
    if runtime_config is None:
        from .config import settings
        runtime_config = RuntimeConfig(settings)
    return runtime_config
