import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timedelta

import config
from intent_global_orchestrator import IntentGlobalOrchestrator
from database_manager import build_company_intent_summary


def test_limit_intent_signals_to_80():
    orchestrator = IntentGlobalOrchestrator()
    signals = []
    for idx in range(90):
        signals.append({"intent_type": "job_post", "title": f"Job {idx}", "date": "2026-01-01"})

    limited = orchestrator._limit_intent_signals(signals, max_items=config.MAX_INTENT_SIGNALS_PER_COMPANY)
    assert len(limited) == config.MAX_INTENT_SIGNALS_PER_COMPANY
    assert limited[0]["title"] == "Job 0"
    assert limited[-1]["title"] == "Job 29"


def test_recency_filter_jobs_and_news():
    orchestrator = IntentGlobalOrchestrator()
    now = datetime.now()

    def parse_date(date_str):
        return datetime.strptime(date_str, "%Y-%m-%d")

    recent_job = {"posted_at": (now - timedelta(days=10)).strftime("%Y-%m-%d")}
    old_job = {"posted_at": (now - timedelta(days=60)).strftime("%Y-%m-%d")}
    recent_news = {"published_at": (now - timedelta(days=90)).strftime("%Y-%m-%d")}
    old_news = {"published_at": (now - timedelta(days=200)).strftime("%Y-%m-%d")}

    assert orchestrator._passes_recency_filter(recent_job, "job_post", parse_date) is True
    assert orchestrator._passes_recency_filter(old_job, "job_post", parse_date) is False
    assert orchestrator._passes_recency_filter(recent_news, "news", parse_date) is True
    assert orchestrator._passes_recency_filter(old_news, "news", parse_date) is False


def test_build_company_intent_summary():
    signals = [
        {"intent_type": "job_post", "title": "Sales Manager", "department": "Sales"},
        {"intent_type": "job_post", "title": "Software Engineer", "department": "Engineering"},
        {"intent_type": "news", "title_and_summary": "Launches a new analytics platform", "news_type": "Product Launch"},
    ]

    summary = build_company_intent_summary("Example Corp", signals)
    assert "Example Corp" in summary
    assert "Sales Manager" in summary or "hiring" in summary.lower() or "news" in summary.lower()


if __name__ == "__main__":
    test_limit_intent_signals_to_80()
    test_recency_filter_jobs_and_news()
    test_build_company_intent_summary()
