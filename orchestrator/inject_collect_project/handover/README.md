Inject-Collect Project — Handover Overview

Purpose

This handover bundle gives new maintainers and stakeholders both a high-level understanding and actionable steps to operate, troubleshoot, and extend the Inject-Collect system.

What Inject-Collect does (high level)

- Orchestrates injection jobs that submit payloads to target systems (APIs, message queues, devices).
- Collects responses, outcomes and telemetry, and persists them for analysis and reporting.
- Provides monitoring, retries, and backfill capabilities to ensure reliability.

Primary audiences

- New maintainers (developers, SREs)
- On-call engineers
- Product / stakeholders needing operational context

Quick orientation

- Project root: (see repo root)
- Key directories:
  - src/        — core orchestrator and adapters
  - config/     — runtime configuration and templates
  - scripts/    — helper scripts for local runs, CI, deploy
  - examples/   — sample payloads and sample pipeline runs
  - docs/       — additional documentation (if present)

Key contacts and access

- Fill CONTACTS.md with owners, escalation, and credential locations.

Next recommended steps for a new joiner

1. Read TECHNICAL.md for architecture and component details.
2. Follow ONBOARDING.md to set up a local dev environment.
3. Run EXAMPLES.md sample workflow to verify local processing.
4. Read RUNBOOK.md to understand operational tasks and alerts.

Placeholders

Many environment-specific values (secrets, hostnames, exact runtimes) are marked TODO in TECHNICAL.md and ONBOARDING.md — update them during handover.