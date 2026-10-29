"""
Demo script: Run the sequence generation pipeline and see results visually.

Usage:
    cd "sequence generator"
    python scripts/demo_sequence.py

This script:
  1. Loads .env config (including GOOGLE_API_KEY)
  2. Takes sample prospect input data
  3. Runs the LangGraph pipeline (generate → sandbox → timezone adjust)
  4. Prints the full sequence with UTC + local time for each step
"""

import os
import sys
import types
import json
import time
import io
import importlib
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Force UTF-8 output on Windows
if os.name == 'nt':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ── Setup: Create package alias for "sequence generator" (space in name) ──
SCRIPT_DIR = Path(__file__).resolve().parent
SEQ_GEN_DIR = SCRIPT_DIR.parent

def _load_pkg_module(pkg_name: str, pkg_dir: Path):
    """Register a directory as a Python package despite non-standard name."""
    init_file = pkg_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# auto-generated for package registration\n")
    spec = importlib.util.spec_from_file_location(
        pkg_name, str(init_file),
        submodule_search_locations=[str(pkg_dir)]
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[pkg_name] = mod
    spec.loader.exec_module(mod)
    return mod

# Register "sequence_generator" as an alias for the "sequence generator" directory
_seq_gen = _load_pkg_module("sequence_generator", SEQ_GEN_DIR)

# Also register sub-packages so relative imports work
for subpkg in ["config", "models", "graph", "graph.nodes", "tools",
               "observability", "temporal", "workflows", "middleware"]:
    subpkg_path = SEQ_GEN_DIR / subpkg.replace(".", "/")
    if subpkg_path.is_dir():
        full_name = f"sequence_generator.{subpkg}"
        init = subpkg_path / "__init__.py"
        if not init.exists():
            init.write_text("")
        try:
            spec = importlib.util.spec_from_file_location(
                full_name, str(init),
                submodule_search_locations=[str(subpkg_path)]
            )
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules[full_name] = mod
                spec.loader.exec_module(mod)
        except Exception:
            pass  # Some subpackages may fail if they have import-time deps

# ── Load .env ──
from dotenv import load_dotenv
load_dotenv(SEQ_GEN_DIR / ".env")

# ── Now import from the sequence generator ──
from sequence_generator.graph.state import GraphState
from sequence_generator.graph.builder import create_graph
from sequence_generator.models.outreach_step import (
    OutreachStep, OutreachSequence, BUSINESS_HOURS_START, BUSINESS_HOURS_END
)
from sequence_generator.config.constants import (
    COUNTRY_TIMEZONE_MAP,
    DEFAULT_TIMEZONE_OFFSET,
    DEFAULT_TIMEZONE_NAME,
    MIN_WAIT_SECONDS,
    MAX_WAIT_SECONDS,
)

# ── Terminal colors for pretty output ──
class C:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    END = "\033[0m"


def banner(text: str, color: str = C.BLUE):
    width = 70
    print(f"\n{color}{C.BOLD}{'=' * width}{C.END}")
    print(f"{color}{C.BOLD}  {text}{C.END}")
    print(f"{color}{C.BOLD}{'=' * width}{C.END}\n")


def section(text: str):
    print(f"\n{C.CYAN}{C.BOLD}--- {text} ---{C.END}")


def kv(key: str, value, indent: int = 2):
    prefix = " " * indent
    print(f"{prefix}{C.BOLD}{key}:{C.END} {value}")


def step_card(step: OutreachStep, tz_offset: int, tz_name: str):
    """Pretty-print a single OutreachStep with UTC and local time."""
    local_tz = timezone(timedelta(hours=tz_offset))
    local_dt = step.scheduled_timestamp.astimezone(local_tz)
    utc_dt = step.scheduled_timestamp

    wait_hrs = step.wait_delay_seconds / 3600
    wait_display = (
        f"{step.wait_delay_seconds}s"
        + (f" (~{wait_hrs:.1f}h)" if step.wait_delay_seconds >= 3600 else "")
    )

    print(f"\n  {C.GREEN}+-- Step {step.step_number}{C.END}")
    print(f"  {C.GREEN}|{C.END}  {C.BOLD}Action:{C.END}  {step.action_type.value}")
    print(f"  {C.GREEN}|{C.END}  {C.BOLD}Channel:{C.END} {step.channel}")
    print(f"  {C.GREEN}|{C.END}  {C.BOLD}UTC Time:{C.END}   {utc_dt.strftime('%Y-%m-%d %H:%M UTC')} ({utc_dt.strftime('%A')})")
    print(f"  {C.GREEN}|{C.END}  {C.BOLD}Local Time:{C.END} {local_dt.strftime('%Y-%m-%d %H:%M')} {tz_name} ({local_dt.strftime('%A')})")
    print(f"  {C.GREEN}|{C.END}  {C.BOLD}Wait Delay:{C.END} {wait_display}")
    print(f"  {C.GREEN}|{C.END}  {C.BOLD}Language:{C.END}  {step.message_language or 'default'}")
    print(f"  {C.GREEN}|{C.END}  {C.DIM}Timing: {step.timing_justification}{C.END}")
    print(f"  {C.GREEN}+--------------------------------------{C.END}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SAMPLE INPUT DATA
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SAMPLE_INPUT = {
    "lead_id": "demo_lead_001",
    "campaign_id": "demo_campaign_2024",
    "entreprise": "NovaTech Solutions",
    "contact_info": {
        "nom": "Amira Ben Salah",
        "full_name": "Amira Ben Salah",
        "titre": "Directrice Marketing",
        "job_title": "Marketing Director",
        "email": "amira.bensalah@novatech.tn",
        "country": "Tunisia",
        "city": "Tunis",
        "location": "Tunis, Tunisia",
        "phone": "+216 71 234 567",
        "linkedin": "linkedin.com/in/amirabensalah",
    },
    "contexte_web": {
        "profil_brut": (
            "Amira Ben Salah est Directrice Marketing chez NovaTech Solutions, "
            "une entreprise tunisienne specialisee dans les solutions IT pour entreprises. "
            "Elle a recemment publie des articles sur LinkedIn concernant la transformation "
            "digitale et l'automatisation des processus marketing en Afrique du Nord. "
            "NovaTech a 150 employes et cherche a s'etendre vers le marche europeen."
        ),
        "offer_context": (
            "AI-powered outreach platform that automates multi-channel B2B sequences "
            "with smart timing, language detection, and human-in-the-loop approval."
        ),
        "icp_description": (
            "B2B companies with 50-500 employees in North Africa and Europe, "
            "looking to improve their outbound sales efficiency."
        ),
    },
    "approval_mode": "per_sequence",
    "research_signals": [
        {
            "type": "linkedin_post",
            "content": "Amira recently published articles on LinkedIn about digital transformation and marketing process automation in North Africa.",
            "strength": "strong",
            "source_url": "linkedin.com/in/amirabensalah/posts",
            "timestamp": "2024-12-10T09:00:00Z",
            "why_relevant": "Shows active thought leadership in digital transformation — perfect hook for an AI outreach platform."
        },
        {
            "type": "company_news",
            "content": "NovaTech Solutions has 150 employees and is expanding toward the European market.",
            "strength": "strong",
            "source_url": "novatech.tn/about",
            "timestamp": "2024-11-15T10:00:00Z",
            "why_relevant": "European expansion means they need scalable outbound tools — direct pain point we solve."
        },
        {
            "type": "job_change",
            "content": "Amira was promoted to Marketing Director 6 months ago, now overseeing the full marketing strategy.",
            "strength": "medium",
            "source_url": "linkedin.com/in/amirabensalah",
            "timestamp": "2024-06-01T08:00:00Z",
            "why_relevant": "New role means she's actively evaluating tools and processes to improve her team's performance."
        },
        {
            "type": "tech_stack",
            "content": "NovaTech currently uses HubSpot for CRM and basic email marketing.",
            "strength": "medium",
            "source_url": "builtwith.com/novatech.tn",
            "timestamp": "2024-10-20T12:00:00Z",
            "why_relevant": "HubSpot users often outgrow basic sequencing — our platform is a natural upgrade path."
        }
    ],
}


def main():
    banner("SEQUENCE GENERATION DEMO", C.BLUE)

    # ── 1. Show Input ──
    section("1. INPUT DATA")
    contact = SAMPLE_INPUT["contact_info"]
    kv("Lead ID", SAMPLE_INPUT["lead_id"])
    kv("Campaign", SAMPLE_INPUT["campaign_id"])
    kv("Company", SAMPLE_INPUT["entreprise"])
    kv("Prospect", f"{contact['full_name']} ({contact['job_title']})")
    kv("Email", contact["email"])
    kv("Location", contact["location"])
    kv("Approval Mode", SAMPLE_INPUT["approval_mode"])

    # ── 2. Preview Timezone Detection ──
    section("2. TIMEZONE & LANGUAGE PREVIEW")
    country = contact["country"].lower()
    tz_offset, tz_name = COUNTRY_TIMEZONE_MAP.get(country, (DEFAULT_TIMEZONE_OFFSET, DEFAULT_TIMEZONE_NAME))
    print(f"  Country '{contact['country']}' -> UTC{tz_offset:+d} ({tz_name})")
    print(f"  Local business hours: {BUSINESS_HOURS_START}:00 - {BUSINESS_HOURS_END}:00 {tz_name}")
    local_start_utc = BUSINESS_HOURS_START - tz_offset
    local_end_utc = BUSINESS_HOURS_END - tz_offset
    print(f"  Equivalent UTC window: {local_start_utc:02d}:00 - {local_end_utc:02d}:00 UTC")

    # ── 3. Build and Run Graph ──
    section("3. RUNNING LANGGRAPH PIPELINE")
    print(f"  {C.DIM}Building graph...{C.END}")
    app, memory = create_graph()

    thread_id = f"demo_thread_{int(time.time())}"
    config = {"configurable": {"thread_id": thread_id}}

    # Prepare initial state
    initial_state = GraphState(
        lead_id=SAMPLE_INPUT["lead_id"],
        campaign_id=SAMPLE_INPUT["campaign_id"],
        entreprise=SAMPLE_INPUT["entreprise"],
        contact_info=SAMPLE_INPUT["contact_info"],
        contexte_web=SAMPLE_INPUT["contexte_web"],
        approval_mode=SAMPLE_INPUT["approval_mode"],
        research_signals=SAMPLE_INPUT.get("research_signals"),
    )

    print(f"  {C.DIM}Invoking graph (thread: {thread_id})...{C.END}")
    print(f"  {C.YELLOW}Calling Gemini for sequence generation...{C.END}")

    start_time = time.time()
    result = app.invoke(initial_state.model_dump(), config)
    elapsed = time.time() - start_time

    print(f"  {C.GREEN}Graph execution complete in {elapsed:.1f}s{C.END}")

    # ── 4. Extract Results ──
    final_state = GraphState(**result)

    section("4. DETECTION RESULTS")
    kv("Detected Language", f"{final_state.detected_language_name} ({final_state.detected_language}) — from country mapping")
    if final_state.validated_sequence:
        seq_lang = final_state.validated_sequence.detected_language
        if seq_lang and seq_lang != final_state.detected_language:
            kv("Sequence Language", f"{seq_lang} — Gemini chose this based on prospect profile")
    tz_off = final_state.detected_timezone if final_state.detected_timezone is not None else 0
    tz_nm = final_state.detected_timezone_name or "UTC"
    kv("Timezone", f"UTC{tz_off:+d} ({tz_nm})")
    kv("Approval Mode", final_state.approval_mode)
    kv("Retry Count", final_state.retry_count)
    kv("Fallback Used", final_state.fallback_triggered)

    # ── 5. Show Sequence ──
    if final_state.validated_sequence:
        seq = final_state.validated_sequence
        tz_off_final = seq.detected_timezone if seq.detected_timezone is not None else tz_off
        tz_nm_final = seq.detected_timezone_name or tz_nm

        section(f"5. GENERATED SEQUENCE ({len(seq.steps)} steps)")
        print(f"  {C.BOLD}Lead:{C.END} {seq.lead_id}")
        print(f"  {C.BOLD}Campaign:{C.END} {seq.campaign_id}")
        print(f"  {C.BOLD}Generated at:{C.END} {seq.generated_at.strftime('%Y-%m-%d %H:%M UTC')}")
        print(f"  {C.BOLD}Language:{C.END} {seq.detected_language}")
        tz_display = f"UTC{tz_off_final:+d}" if tz_off_final is not None else "UTC+0"
        print(f"  {C.BOLD}Timezone:{C.END} {tz_display} ({tz_nm_final})")

        for step in seq.steps:
            step_card(step, tz_off_final, tz_nm_final)

        # ── 6. Sandbox Adjustments ──
        section("6. SANDBOX ADJUSTMENTS")
        if final_state.sandbox_adjustments:
            for adj in final_state.sandbox_adjustments:
                print(f"  {C.YELLOW}! Step {adj['step_number']} -- {adj['field']}:{C.END} {adj['reason']}")
                if "original_local" in adj:
                    print(f"    {C.DIM}Local time: {adj.get('original_local', '?')} -> {adj.get('adjusted_local', '?')}{C.END}")
                elif "original_value" in adj:
                    print(f"    {C.DIM}{adj['original_value']} -> {adj['adjusted_value']}{C.END}")
        else:
            print(f"  {C.GREEN}No sandbox adjustments needed -- LLM output was within bounds.{C.END}")

        # ── 7. Timeline Visualization ──
        section("7. TIMELINE")
        local_tz = timezone(timedelta(hours=tz_off_final))
        for i, step in enumerate(seq.steps):
            local_dt = step.scheduled_timestamp.astimezone(local_tz)
            day_label = local_dt.strftime("%a %b %d")
            time_label = local_dt.strftime("%H:%M")
            connector = "|" if i < len(seq.steps) - 1 else " "
            print(f"  {C.CYAN}{day_label} {time_label} {tz_nm_final}{C.END} --- {step.action_type.value} ({step.channel})")
            if i < len(seq.steps) - 1:
                next_step = seq.steps[i + 1]
                wait_hrs = next_step.wait_delay_seconds / 3600
                print(f"  {C.DIM}{connector}  wait {next_step.wait_delay_seconds}s (~{wait_hrs:.1f}h){C.END}")

        # ── 8. Temporal Payload Preview ──
        section("8. TEMPORAL PAYLOAD PREVIEW")
        if final_state.temporal_payload:
            payload_str = json.dumps(final_state.temporal_payload, indent=2, default=str)
            lines = payload_str.split("\n")
            if len(lines) > 40:
                print(f"  {C.DIM}" + "\n".join(lines[:40]) + f"{C.END}")
                print(f"  {C.DIM}  ... ({len(lines) - 40} more lines){C.END}")
            else:
                print(f"  {C.DIM}{payload_str}{C.END}")
        else:
            print(f"  {C.YELLOW}No temporal payload (graph paused at interrupt_before dispatch).{C.END}")
            print(f"  {C.DIM}This is expected -- the approval gate paused before dispatch to Temporal.{C.END}")
    else:
        section("5. GENERATION FAILED")
        print(f"  {C.RED}No validated sequence produced.{C.END}")
        if final_state.validation_errors:
            print(f"  {C.RED}Validation errors:{C.END}")
            for err in final_state.validation_errors:
                print(f"    - {err[:200]}")

    # ── Summary ──
    banner("DEMO COMPLETE", C.GREEN)
    print(f"  The pipeline:")
    seq_lang_display = final_state.validated_sequence.detected_language if final_state.validated_sequence else final_state.detected_language
    print(f"    1. Detected language from country -> {final_state.detected_language_name} ({final_state.detected_language})")
    if seq_lang_display and seq_lang_display != final_state.detected_language:
        print(f"       Gemini chose -> {seq_lang_display} (based on prospect profile)")
    print(f"    2. Detected timezone from prospect's country -> UTC{tz_off:+d}")
    print(f"    3. Generated sequence via Gemini (strategy + timing)")
    print(f"    4. Sandboxed timestamps to prospect-local business hours ({BUSINESS_HOURS_START}:00-{BUSINESS_HOURS_END}:00 {tz_nm})")
    print(f"    5. Paused at approval gate (interrupt_before dispatch)")
    print()
    print(f"  Next step in production:")
    print(f"    - Human reviews & approves the sequence")
    print(f"    - Graph resumes -> generates messages via Message Generator API")
    print(f"    - Dispatches to Temporal.io for durable execution with sleep between steps")
    print()


if __name__ == "__main__":
    main()
