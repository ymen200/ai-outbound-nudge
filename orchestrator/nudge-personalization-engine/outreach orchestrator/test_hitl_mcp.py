"""
End-to-end HITL (Human-in-the-Loop) MCP test.

Tests the full approval workflow through the orchestrator's MCP server:
1. run_outreach_pipeline → returns status='awaiting_approval' + thread_id
2. get_outreach_status → surfaces the paused pipeline
3. approve_pipeline → dispatches to Temporal
4. Verify the dispatch was confirmed

This is a unit test that mocks the downstream clients (Sequence Generator, Message Generator)
since we can't run live services in the test environment.
"""

import sys
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

# Add orchestrator to path
_ORCH_DIR = Path(__file__).resolve().parent
if str(_ORCH_DIR) not in sys.path:
    sys.path.insert(0, str(_ORCH_DIR))


@pytest.fixture
def mock_seq_client():
    """Mock SequenceGeneratorClient with approve_sequence method."""
    client = AsyncMock()
    client.generate_sequence.return_value = {
        "thread_id": "test-thread-123",
        "status": "awaiting_approval",
        "sequence": {"steps": [{"step_number": 1, "action_type": "EMAIL_1"}]},
    }
    client.approve_sequence.return_value = {
        "status": "dispatched",
        "thread_id": "test-thread-123",
        "temporal_workflow_id": "wf-abc-123",
    }
    client.get_observability.return_value = {
        "total_calls": 5,
        "total_tokens_in": 1000,
        "total_tokens_out": 500,
        "total_tokens": 1500,
    }
    client.get_paused_threads.return_value = {
        "paused_threads": [
            {
                "thread_id": "test-thread-123",
                "paused_at": "dispatch_to_temporal",
                "entreprise": "TestCorp",
                "lead_id": "test-lead-001",
                "contact_info": {
                    "full_name": "Jane Doe",
                    "email": "jane@test.com",
                    "country": "United States",
                },
            }
        ],
    }
    client.health.return_value = {"status": "ok"}
    return client


@pytest.fixture
def mock_msg_client():
    """Mock MessageGeneratorClient."""
    client = AsyncMock()
    client.health.return_value = {"status": "ok"}
    client.get_observability.return_value = {
        "total_calls": 3,
        "total_tokens_in": 600,
        "total_tokens_out": 300,
        "total_tokens": 900,
    }
    return client


@pytest.mark.asyncio
async def test_hitl_mcp_workflow(mock_seq_client, mock_msg_client):
    """Test the full HITL approval workflow through MCP tools."""
    from app.mcp_server import call_tool
    from app.observability import ObservabilityAggregator

    mock_agg = MagicMock(spec=ObservabilityAggregator)
    mock_agg.seq_client = mock_seq_client
    mock_agg.msg_client = mock_msg_client
    mock_agg.check_health = AsyncMock(return_value={
        "sequence_generator": {"status": "ok"},
        "message_generator": {"status": "ok"},
    })
    mock_agg.collect_full_snapshot = AsyncMock(return_value={})

    with patch("app.mcp_server._get_aggregator", return_value=mock_agg):
        with patch("app.mcp_server.run_orchestrator", new_callable=AsyncMock) as mock_run:
            with patch("app.mcp_server.SequenceGeneratorClient", return_value=mock_seq_client):
                mock_run.return_value = {
                    "status": "awaiting_approval",
                    "thread_id": "test-thread-123",
                    "sequence_result": {
                        "thread_id": "test-thread-123",
                        "status": "awaiting_approval",
                    },
                }

                # ── Step 1: run_outreach_pipeline → awaiting_approval ──
                run_result = await call_tool("run_outreach_pipeline", {
                    "lead_id": "test-lead-001",
                    "campaign_id": "test-campaign",
                    "entreprise": "TestCorp",
                    "contact_full_name": "Jane Doe",
                    "contact_email": "jane@test.com",
                    "contact_country": "United States",
                })
                run_data = json.loads(run_result[0].text)

                assert run_data["status"] == "awaiting_approval", \
                    f"Expected awaiting_approval, got {run_data['status']}"
                assert "thread_id" in run_data, "thread_id missing from run result"
                thread_id = run_data["thread_id"]
                assert thread_id == "test-thread-123"

                # ── Step 2: get_outreach_status → surfaces paused pipeline ──
                status_result = await call_tool("get_outreach_status", {})
                status_data = json.loads(status_result[0].text)

                assert "pipeline_status" in status_data, \
                    "pipeline_status missing from get_outreach_status"
                assert "paused_threads" in status_data["pipeline_status"], \
                    "paused_threads missing from pipeline_status"
                assert "paused_count" in status_data["pipeline_status"], \
                    "paused_count missing from pipeline_status"
                assert status_data["pipeline_status"]["paused_count"] >= 1, \
                    "Expected at least 1 paused thread"
                # Verify the specific thread we just created is visible
                paused_ids = [t["thread_id"] for t in status_data["pipeline_status"]["paused_threads"]]
                assert thread_id in paused_ids, \
                    f"Expected thread {thread_id} in paused_threads, got {paused_ids}"
                assert "note" in status_data["pipeline_status"], \
                    "pipeline_status.note missing"
                assert "sequence_generator_observability" in status_data["pipeline_status"], \
                    "sequence_generator_observability missing from pipeline_status"

                # ── Step 3: approve_pipeline → dispatch confirmed ──
                approve_result = await call_tool("approve_pipeline", {
                    "thread_id": thread_id,
                    "approved": True,
                })
                approve_data = json.loads(approve_result[0].text)

                assert approve_data["status"] == "dispatched", \
                    f"Expected dispatched, got {approve_data['status']}"
                assert approve_data["thread_id"] == thread_id, \
                    "thread_id mismatch in approve result"
                assert "temporal_workflow_id" in approve_data, \
                    "temporal_workflow_id missing from approve result"

                # ── Step 4: Verify approve_sequence was called with correct args ──
                mock_seq_client.approve_sequence.assert_called_once_with(
                    thread_id=thread_id,
                    approved=True,
                    feedback=None,
                )


@pytest.mark.asyncio
async def test_hitl_rejection_with_feedback(mock_seq_client, mock_msg_client):
    """Test rejection with feedback regenerates the sequence."""
    from app.mcp_server import call_tool
    from app.observability import ObservabilityAggregator

    mock_agg = MagicMock(spec=ObservabilityAggregator)
    mock_agg.seq_client = mock_seq_client
    mock_agg.msg_client = mock_msg_client
    mock_agg.check_health = AsyncMock(return_value={
        "sequence_generator": {"status": "ok"},
        "message_generator": {"status": "ok"},
    })
    mock_agg.collect_full_snapshot = AsyncMock(return_value={})

    with patch("app.mcp_server._get_aggregator", return_value=mock_agg):
        with patch("app.mcp_server.run_orchestrator", new_callable=AsyncMock) as mock_run:
            with patch("app.mcp_server.SequenceGeneratorClient", return_value=mock_seq_client):
                mock_run.return_value = {
                    "status": "awaiting_approval",
                    "thread_id": "test-thread-456",
                    "sequence_result": {
                        "thread_id": "test-thread-456",
                        "status": "awaiting_approval",
                    },
                }

                # Run pipeline → awaiting_approval
                run_result = await call_tool("run_outreach_pipeline", {
                    "lead_id": "test-lead-002",
                    "campaign_id": "test-campaign",
                    "entreprise": "TestCorp",
                    "contact_full_name": "John Doe",
                    "contact_email": "john@test.com",
                })
                run_data = json.loads(run_result[0].text)
                thread_id = run_data["thread_id"]

                # Reject with feedback
                reject_result = await call_tool("approve_pipeline", {
                    "thread_id": thread_id,
                    "approved": False,
                    "feedback": "Add more LinkedIn touches",
                })

                # Verify approve_sequence was called with feedback
                mock_seq_client.approve_sequence.assert_called_once_with(
                    thread_id=thread_id,
                    approved=False,
                    feedback="Add more LinkedIn touches",
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
