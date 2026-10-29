"""
Observability infrastructure for the Sequence Generator.

Provides:
- PromptRecord: dataclass capturing every Gemini call
- PromptStore: thread-safe in-memory history (capped, FIFO eviction)
- RuntimeConfig: mutable overlay on top of env vars for global orchestrator overrides
"""

import threading
import time
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


# ---------------------------------------------------------------------------
# PromptRecord
# ---------------------------------------------------------------------------

@dataclass
class PromptRecord:
    timestamp: str
    module: str                 # "sequence_generator"
    agent_step: str             # "sequence_generator", "language_detector", etc.
    prompt: str
    response: Optional[str] = None
    tokens_in: int = 0          # actual input tokens from provider usageMetadata
    tokens_out: int = 0         # actual output tokens from provider usageMetadata
    model_used: str = "primary"
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# PromptStore
# ---------------------------------------------------------------------------

class PromptStore:
    """Thread-safe in-memory prompt history with FIFO eviction."""

    MAX_RECORDS = 1000

    def __init__(self, module: str = "sequence_generator"):
        self._module = module
        self._records: List[PromptRecord] = []
        self._lock = threading.Lock()

    def record(self, rec: PromptRecord) -> None:
        rec.module = self._module
        with self._lock:
            if len(self._records) >= self.MAX_RECORDS:
                self._records.pop(0)
            self._records.append(rec)

    def get_history(
        self,
        limit: int = 50,
        agent_step: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with self._lock:
            records = list(reversed(self._records))
        if agent_step:
            records = [r for r in records if r.agent_step == agent_step]
        return [r.to_dict() for r in records[:limit]]

    def get_summary(self) -> Dict[str, Any]:
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
        with self._lock:
            count = len(self._records)
            self._records.clear()
        return count


# ---------------------------------------------------------------------------
# RuntimeConfig — mutable overlay on top of env-based config
# ---------------------------------------------------------------------------

ALLOWED_OVERRIDE_KEYS = {
    "GEMINI_TEMPERATURE",
    "GEMINI_MAX_TOKENS",
    "GEMINI_MODEL",
    "GEMINI_FALLBACK_MODEL",
    "MAX_RETRIES",
    "LOG_LEVEL",
    "DEBUG_MODE",
}


class RuntimeConfig:
    """Mutable overlay on top of os.environ for runtime overrides."""

    def __init__(self):
        self._overrides: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._overrides:
                return self._overrides[key]
        return os.getenv(key, default)

    def get_float(self, key: str, default: float = 0.0) -> float:
        return float(self.get(key, default))

    def get_int(self, key: str, default: int = 0) -> int:
        return int(self.get(key, default))

    def set(self, key: str, value: Any) -> bool:
        if key not in ALLOWED_OVERRIDE_KEYS:
            return False
        with self._lock:
            self._overrides[key] = value
        return True

    def reset(self, key: Optional[str] = None) -> None:
        with self._lock:
            if key:
                self._overrides.pop(key, None)
            else:
                self._overrides.clear()

    def get_all_overrides(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._overrides)


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

prompt_store = PromptStore(module="sequence_generator")
runtime_config = RuntimeConfig()
