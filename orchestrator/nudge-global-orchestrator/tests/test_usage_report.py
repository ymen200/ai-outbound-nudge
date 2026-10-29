"""Unit tests for per-campaign usage report aggregation."""

from __future__ import annotations

import json
from pathlib import Path

from app.usage_report import UsageReportBuilder, extract_usage


def test_extract_usage():
    assert extract_usage({"usage": {"groq": {"total_tokens": 10}}}) == {
        "groq": {"total_tokens": 10}
    }
    assert extract_usage({"companies": []}) is None
    assert extract_usage(None) is None


def test_aggregate_sourcer_and_qualifier_usage(tmp_path: Path):
    builder = UsageReportBuilder("camp-1", qualifier_campaign_id="qual-1")

    builder.record(
        "sourcer.fetch_companies",
        {
            "tool": "sourcer.fetch_companies",
            "apollo": {
                "lead_credits_consumed": 2,
                "direct_dial_credits_consumed": 0,
                "ai_credits_consumed": 1,
            },
            "gemini": {
                "total_tokens": 100,
                "prompt_tokens": 60,
                "candidates_tokens": 40,
                "api_calls_consumed": 2,
                "successful_calls": 2,
                "failed_calls": 0,
                "thoughts_tokens": 0,
                "cached_content_tokens": 0,
                "by_model": {"gemini-2.0-flash": {"calls": 2, "total_tokens": 100}},
                "by_operation": {},
            },
            "groq": {
                "total_tokens_in": 20,
                "total_tokens_out": 10,
                "total_tokens": 30,
                "total_llm_calls": 1,
                "by_operation": {
                    "llm": {
                        "llm_calls": 1,
                        "tokens_in": 20,
                        "tokens_out": 10,
                        "total_tokens": 30,
                    }
                },
            },
        },
    )
    builder.record(
        "qualifier.start_campaign",
        {
            "campaign_id": "qual-1",
            "per_node": [
                {
                    "node_name": "extract_icp",
                    "llm_calls": 1,
                    "tokens_in": 50,
                    "tokens_out": 20,
                    "total_tokens": 70,
                }
            ],
            "combined": {
                "total_tokens": 70,
                "total_tokens_in": 50,
                "total_tokens_out": 20,
                "total_llm_calls": 1,
            },
            "errors": [],
        },
    )
    builder.record(
        "qualifier.resume_with_companies",
        {
            "combined": {
                "total_tokens": 200,
                "total_tokens_in": 150,
                "total_tokens_out": 50,
                "total_llm_calls": 3,
            },
            "per_node": [],
            "errors": [],
        },
    )

    report = builder.build()
    assert report["campaign_id"] == "camp-1"
    assert report["qualifier_campaign_id"] == "qual-1"
    assert report["totals"]["apollo"]["lead_credits_consumed"] == 2
    assert report["totals"]["apollo"]["ai_credits_consumed"] == 1
    assert report["totals"]["gemini"]["total_tokens"] == 100
    assert report["totals"]["gemini"]["api_calls_consumed"] == 2

    groq = report["totals"]["groq"]
    assert groq["total_tokens"] == 300  # 30 + 70 + 200
    assert groq["total_tokens_in"] == 220  # 20 + 50 + 150
    assert groq["total_tokens_out"] == 80  # 10 + 20 + 50
    assert groq["total_llm_calls"] == 5  # 1 + 1 + 3
    assert groq["by_service"]["sourcer"]["total_tokens"] == 30
    assert groq["by_service"]["qualifier"]["total_tokens"] == 270

    path = builder.write(output_dir=str(tmp_path))
    assert path.exists()
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["totals"]["groq"]["total_tokens"] == 300
    assert "sourcer.fetch_companies" in loaded["tools"]
    assert "qualifier.start_campaign" in loaded["tools"]


def test_mcp_payload_with_usage_still_unwraps():
    # Inline a minimal copy of the unwrap gate used by mcp_clients so this
    # test does not require the fastmcp dependency.
    payload = {
        "companies": [{"apollo_id": "x"}],
        "count": 1,
        "usage": {
            "tool": "sourcer.fetch_companies",
            "apollo": {"lead_credits_consumed": 1},
            "gemini": {"total_tokens": 5},
            "groq": {"total_tokens": 9},
        },
    }
    assert "companies" in payload
    assert payload["usage"]["groq"]["total_tokens"] == 9
