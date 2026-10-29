"""
tests/test_usage_tracking.py
───────────────────────────
Unit test for usage tracking integration without requiring full pipeline.

Tests:
  1. UsageAccumulator records token counts correctly
  2. GroqUsageCallback captures token usage from LLM responses
  3. make_callback creates a valid callback handler
  4. get_campaign_accumulator returns the same instance for same campaign_id
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(ROOT_DIR).parent / ".env")

from utils.usage_tracker import (
    get_campaign_accumulator,
    get_usage_summary,
    clear_campaign_accumulator,
    make_callback,
    UsageAccumulator,
)


def test_accumulator_basic():
    """Test that accumulator records token counts correctly."""
    print("\n--- Test 1: Accumulator Basic Recording ---")
    
    acc = UsageAccumulator("test-campaign-1")
    
    # Record some token usage
    acc.record(tokens_in=100, tokens_out=50, node_name="test_node")
    acc.record(tokens_in=200, tokens_out=75, node_name="test_node")
    acc.record(tokens_in=50, tokens_out=25, node_name="another_node")
    
    summary = acc.get_summary()
    
    print(f"  Per-node breakdown: {len(summary.per_node)} nodes")
    for node_usage in summary.per_node:
        print(f"    - {node_usage.node_name}: {node_usage.llm_calls} calls, "
              f"{node_usage.tokens_in} in, {node_usage.tokens_out} out, "
              f"{node_usage.total_tokens} total")
    
    print(f"  Combined totals: {summary.combined}")
    
    assert len(summary.per_node) == 2
    assert summary.combined["total_llm_calls"] == 3
    assert summary.combined["total_tokens_in"] == 350
    assert summary.combined["total_tokens_out"] == 150
    assert summary.combined["total_tokens"] == 500
    
    print("  ✓ Accumulator basic recording works correctly")
    return True


def test_campaign_accumulator_registry():
    """Test that get_campaign_accumulator returns same instance for same campaign_id."""
    print("\n--- Test 2: Campaign Accumulator Registry ---")
    
    acc1 = get_campaign_accumulator("test-campaign-2")
    acc2 = get_campaign_accumulator("test-campaign-2")
    acc3 = get_campaign_accumulator("test-campaign-3")
    
    print(f"  acc1 is acc2: {acc1 is acc2}")
    print(f"  acc1 is acc3: {acc1 is acc3}")
    
    assert acc1 is acc2  # Same campaign_id should return same instance
    assert acc1 is not acc3  # Different campaign_id should return different instance
    
    # Clean up
    clear_campaign_accumulator("test-campaign-2")
    clear_campaign_accumulator("test-campaign-3")
    
    print("  ✓ Campaign accumulator registry works correctly")
    return True


def test_make_callback():
    """Test that make_callback creates a valid GroqUsageCallback."""
    print("\n--- Test 3: Make Callback ---")
    
    acc = get_campaign_accumulator("test-campaign-4")
    callback = make_callback(acc, "test_node")
    
    print(f"  Callback type: {type(callback).__name__}")
    print(f"  Callback has on_llm_end method: {hasattr(callback, 'on_llm_end')}")
    
    assert callback is not None
    assert hasattr(callback, 'on_llm_end')
    
    # Clean up
    clear_campaign_accumulator("test-campaign-4")
    
    print("  ✓ make_callback creates valid callback handler")
    return True


def test_get_usage_summary():
    """Test that get_usage_summary returns a dict suitable for JSON serialization."""
    print("\n--- Test 4: Get Usage Summary ---")
    
    acc = get_campaign_accumulator("test-campaign-5")
    acc.record(tokens_in=100, tokens_out=50, node_name="node1")
    acc.record(tokens_in=200, tokens_out=100, node_name="node2")
    
    summary_dict = get_usage_summary(acc)
    
    print(f"  Summary is dict: {isinstance(summary_dict, dict)}")
    print(f"  Summary keys: {list(summary_dict.keys())}")
    print(f"  Campaign ID: {summary_dict.get('campaign_id')}")
    print(f"  Per-node count: {len(summary_dict.get('per_node', []))}")
    print(f"  Combined totals: {summary_dict.get('combined')}")
    
    assert isinstance(summary_dict, dict)
    assert summary_dict['campaign_id'] == 'test-campaign-5'
    assert len(summary_dict['per_node']) == 2
    assert summary_dict['combined']['total_llm_calls'] == 2
    
    # Clean up
    clear_campaign_accumulator("test-campaign-5")
    
    print("  ✓ get_usage_summary returns valid dict")
    return True


def test_callback_with_mock_llm_response():
    """Test that GroqUsageCallback correctly extracts token usage from mock LLM response."""
    print("\n--- Test 5: Callback with Mock LLM Response ---")
    
    from langchain_core.outputs import LLMResult
    from langchain_core.messages import AIMessage
    
    acc = get_campaign_accumulator("test-campaign-6")
    callback = make_callback(acc, "test_node")
    
    # Create a mock LLM response with token usage
    mock_response = LLMResult(
        generations=[],
        llm_output={
            "token_usage": {
                "prompt_tokens": 150,
                "completion_tokens": 75,
                "total_tokens": 225,
            }
        }
    )
    
    # Call the callback
    callback.on_llm_end(mock_response)
    
    summary = acc.get_summary()
    
    print(f"  Recorded calls: {summary.combined['total_llm_calls']}")
    print(f"  Recorded tokens_in: {summary.combined['total_tokens_in']}")
    print(f"  Recorded tokens_out: {summary.combined['total_tokens_out']}")
    
    assert summary.combined['total_llm_calls'] == 1
    assert summary.combined['total_tokens_in'] == 150
    assert summary.combined['total_tokens_out'] == 75
    
    # Clean up
    clear_campaign_accumulator("test-campaign-6")
    
    print("  ✓ Callback correctly extracts token usage from LLM response")
    return True


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  USAGE TRACKING UNIT TESTS")
    print("=" * 70)
    
    tests = [
        test_accumulator_basic,
        test_campaign_accumulator_registry,
        test_make_callback,
        test_get_usage_summary,
        test_callback_with_mock_llm_response,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"  ✗ {test.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 70)
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    
    if failed == 0:
        print("  ✓ ALL TESTS PASSED - Usage tracking integration is working correctly")
    else:
        print(f"  ✗ {failed} test(s) failed")
