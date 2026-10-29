"""
utils/usage_tracker.py
───────────────────────
LLM token usage tracking for the Strategic Qualifier pipeline.

Tracks Groq token consumption per node by intercepting LangChain's
llm_end callback — no external observability platform required.

How it works:
  1. GroqUsageCallback is a LangChain BaseCallbackHandler that fires
     on every llm_end event and records prompt/completion/total tokens
     from the response metadata Groq returns on every call.

  2. UsageAccumulator holds a running total across all LLM calls,
     keyed by node_name so you get per-node breakdown.

  3. Each node that makes LLM calls receives the callback handler via
     the track_node_usage() context manager, which sets the current
     active node so the callback knows which bucket to write into.

  4. At the end of a campaign, get_usage_summary() returns a typed
     UsageSummary with per-node breakdown + combined totals.

Usage in nodes.py:
    from utils.usage_tracker import get_campaign_accumulator, track_node_usage

    # In score_and_rank_node:
    accumulator = get_campaign_accumulator(campaign_id)
    with track_node_usage(accumulator, "score_and_rank"):
        firm_results = calculate_company_score(co, icp, state_weights, llm, firm_weights)

Usage in server.py:
    from utils.usage_tracker import (
        get_campaign_accumulator,
        get_usage_summary,
        clear_campaign_accumulator,
    )

    # After pipeline completes:
    accumulator = get_campaign_accumulator(campaign_id)
    summary     = get_usage_summary(accumulator)
    # summary is a dict — store in DB and return in tool output
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Union

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ── Per-node usage record ─────────────────────────────────────────────────────

class NodeUsage(BaseModel):
    """Token usage for a single node."""
    node_name:        str   = Field(..., description="Node that made the LLM calls.")
    llm_calls:        int   = Field(0,   description="Number of LLM calls made by this node.")
    tokens_in:        int   = Field(0,   description="Total prompt tokens consumed.")
    tokens_out:       int   = Field(0,   description="Total completion tokens generated.")
    total_tokens:     int   = Field(0,   description="Total tokens (in + out).")


# ── Combined usage summary ────────────────────────────────────────────────────

class UsageSummary(BaseModel):
    """
    Full token usage summary for a campaign.
    Returned in MCP tool output and stored in the campaigns table.
    """
    campaign_id:  str              = Field(..., description="Campaign this usage belongs to.")
    per_node:     List[NodeUsage]  = Field(default_factory=list, description="Per-node breakdown.")
    combined: Dict[str, int]       = Field(
        default_factory=dict,
        description=(
            "Aggregate across all nodes: total_tokens, total_tokens_in, "
            "total_tokens_out, total_llm_calls."
        ),
    )
    errors: List[str] = Field(
        default_factory=list,
        description="Any errors encountered during usage collection.",
    )


# ══════════════════════════════════════════════════════════════════════════════
# ACCUMULATOR
# ══════════════════════════════════════════════════════════════════════════════

class UsageAccumulator:
    """
    Thread-safe accumulator that collects token counts per node
    across the lifetime of a campaign.

    One accumulator is created per campaign_id and held in the
    module-level _accumulators registry until explicitly cleared.
    """

    def __init__(self, campaign_id: str):
        self.campaign_id  = campaign_id
        self._lock        = threading.Lock()
        self._active_node: Optional[str] = None
        # node_name → {"llm_calls": int, "tokens_in": int, "tokens_out": int}
        self._data: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"llm_calls": 0, "tokens_in": 0, "tokens_out": 0}
        )

    def set_active_node(self, node_name: Optional[str]) -> None:
        with self._lock:
            self._active_node = node_name

    def record(
        self,
        tokens_in:  int,
        tokens_out: int,
        node_name:  Optional[str] = None,
    ) -> None:
        """
        Record token usage for one LLM call.
        Uses node_name if provided, otherwise falls back to _active_node.
        Falls back to 'unknown' if neither is set.
        """
        bucket = node_name or self._active_node or "unknown"
        with self._lock:
            self._data[bucket]["llm_calls"]  += 1
            self._data[bucket]["tokens_in"]  += tokens_in
            self._data[bucket]["tokens_out"] += tokens_out

    def get_summary(self) -> UsageSummary:
        """Build a typed UsageSummary from accumulated data."""
        with self._lock:
            per_node = [
                NodeUsage(
                    node_name    = node,
                    llm_calls    = counts["llm_calls"],
                    tokens_in    = counts["tokens_in"],
                    tokens_out   = counts["tokens_out"],
                    total_tokens = counts["tokens_in"] + counts["tokens_out"],
                )
                for node, counts in self._data.items()
            ]

        total_llm_calls = sum(n.llm_calls    for n in per_node)
        total_tokens_in = sum(n.tokens_in    for n in per_node)
        total_tokens_out= sum(n.tokens_out   for n in per_node)
        total_tokens    = sum(n.total_tokens for n in per_node)

        return UsageSummary(
            campaign_id = self.campaign_id,
            per_node    = per_node,
            combined    = {
                "total_tokens":      total_tokens,
                "total_tokens_in":   total_tokens_in,
                "total_tokens_out":  total_tokens_out,
                "total_llm_calls":   total_llm_calls,
            },
            errors = [],
        )


# ── Module-level registry: campaign_id → UsageAccumulator ────────────────────

_accumulators: Dict[str, UsageAccumulator] = {}
_registry_lock = threading.Lock()


def get_campaign_accumulator(campaign_id: str) -> UsageAccumulator:
    """
    Get or create the UsageAccumulator for a campaign.
    Safe to call multiple times — always returns the same instance
    for the same campaign_id within a process lifetime.
    """
    with _registry_lock:
        if campaign_id not in _accumulators:
            _accumulators[campaign_id] = UsageAccumulator(campaign_id)
        return _accumulators[campaign_id]


def get_usage_summary(accumulator: UsageAccumulator) -> Dict[str, Any]:
    """
    Return the usage summary as a plain dict (for JSON serialization).
    """
    return accumulator.get_summary().model_dump()


def clear_campaign_accumulator(campaign_id: str) -> None:
    """
    Remove the accumulator for a campaign once it's completed.
    Call this after storing the usage summary to free memory.
    """
    with _registry_lock:
        _accumulators.pop(campaign_id, None)


# ══════════════════════════════════════════════════════════════════════════════
# LANGCHAIN CALLBACK HANDLER
# ══════════════════════════════════════════════════════════════════════════════

class GroqUsageCallback(BaseCallbackHandler):
    """
    LangChain callback handler that captures token usage from every
    Groq LLM response and writes it into the campaign's UsageAccumulator.

    Groq returns token counts in response_metadata on every call:
        {
            "token_usage": {
                "prompt_tokens":     245,
                "completion_tokens": 87,
                "total_tokens":      332,
            }
        }

    This handler fires automatically on every llm_end event —
    no changes needed in scoring.py or persona_ranker.py.

    Usage:
        callback   = GroqUsageCallback(accumulator, node_name="score_and_rank")
        result     = llm.invoke(prompt, config={"callbacks": [callback]})
    """

    def __init__(self, accumulator: UsageAccumulator, node_name: str):
        super().__init__()
        self._accumulator = accumulator
        self._node_name   = node_name

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        """
        Fires after every LLM call completes.
        Extracts token counts from Groq's response metadata.
        """
        try:
            # LLMResult.llm_output contains the raw provider response
            llm_output = response.llm_output or {}

            # Groq puts token usage here via LangChain's standard key
            token_usage = llm_output.get("token_usage") or {}

            tokens_in  = int(token_usage.get("prompt_tokens",     0))
            tokens_out = int(token_usage.get("completion_tokens",  0))

            if tokens_in == 0 and tokens_out == 0:
                # Fallback: try generations[0][0].generation_info
                # Some LangChain-Groq versions put it here instead
                for gen_list in (response.generations or []):
                    for gen in gen_list:
                        info = getattr(gen, "generation_info", None) or {}
                        usage = info.get("usage") or {}
                        tokens_in  = int(usage.get("prompt_tokens",     0))
                        tokens_out = int(usage.get("completion_tokens",  0))
                        if tokens_in > 0 or tokens_out > 0:
                            break
                    if tokens_in > 0 or tokens_out > 0:
                        break

            self._accumulator.record(
                tokens_in  = tokens_in,
                tokens_out = tokens_out,
                node_name  = self._node_name,
            )

            logger.debug(
                "groq_usage node=%s tokens_in=%d tokens_out=%d",
                self._node_name, tokens_in, tokens_out,
            )

        except Exception as exc:
            # Never let the callback crash the pipeline
            logger.warning("GroqUsageCallback.on_llm_end failed: %s", exc)


# ══════════════════════════════════════════════════════════════════════════════
# CONTEXT MANAGER FOR NODES
# ══════════════════════════════════════════════════════════════════════════════

@contextmanager
def track_node_usage(accumulator: UsageAccumulator, node_name: str):
    """
    Context manager that sets the active node on the accumulator
    for the duration of a node's execution.

    Use this in nodes that make LLM calls directly (not via the
    callback — this is the fallback for calls that don't pass
    the callback explicitly).

    Usage:
        accumulator = get_campaign_accumulator(campaign_id)
        with track_node_usage(accumulator, "score_and_rank"):
            result = calculate_company_score(...)
    """
    accumulator.set_active_node(node_name)
    try:
        yield accumulator
    finally:
        accumulator.set_active_node(None)


def make_callback(accumulator: UsageAccumulator, node_name: str) -> GroqUsageCallback:
    """
    Convenience function to create a GroqUsageCallback for a node.
    Pass the returned callback into llm.invoke() or llm.with_structured_output().invoke()
    via the config parameter.

    Usage:
        cb     = make_callback(accumulator, "score_and_rank")
        result = llm.invoke(prompt, config={"callbacks": [cb]})

        # Or with structured output:
        structured_llm = llm.with_structured_output(MySchema)
        result = structured_llm.invoke(prompt, config={"callbacks": [cb]})
    """
    return GroqUsageCallback(accumulator, node_name)