Inject-Collect — Operational Runbook

Purpose

Runbook for on-call and ops teams to run routine tasks, respond to incidents, and perform maintenance.

Service status checks

- Health endpoints:
  - Orchestrator: http://<ORCHESTRATOR_HOST>:<PORT>/health
  - Injector X: http://<INJECTOR_HOST>:<PORT>/health
  - Collector X: http://<COLLECTOR_HOST>:<PORT>/health

- Basic checks:
  - Verify process is up (systemd/k8s pods)
  - Check logs for ERROR/CRITICAL
  - Verify DB connectivity: run a simple SELECT 1

Start / stop / restart

- Local (scripts):
  - Start: scripts/start-local.sh
  - Stop: scripts/stop-local.sh
  - Restart: scripts/restart-local.sh

- Kubernetes (example):
  - kubectl rollout restart deployment/injector
  - kubectl get pods -l app=inject-collect -o wide

Responding to alerts

- Alert: job failure rate spike
  1. Check recent job failures: query jobs table ORDER BY updated_at DESC LIMIT 50
  2. Inspect error messages in logs for root cause
  3. If transient (network timeout), consider increasing retries or backoff temporarily
  4. If caused by target changes, roll back or update injector adapter

- Alert: backlog/backlog growth
  1. Check consumer lag (if using broker) and DB write latency
  2. Scale collectors/injectors horizontally
  3. If downstream target is slow, apply rate limiting or throttle backfill

- Alert: database connection failures
  1. Validate DB endpoint and credentials in config
  2. Check network/DNS
  3. Restart app pods after confirming DB availability

Maintenance tasks

- Backups:
  - DB backups: ensure automated snapshots in place; verify restores periodically.
  - Object store: lifecycle policies, periodic verification of sample payloads.

- Schema migrations:
  1. Create migration script under db/migrations
  2. Run migrations in staging; smoke-test
  3. Run migrations in production during maintenance window or via rolling migration

Runbook snippets (commands)

- List failing jobs (SQL example):
  SELECT id, status, attempts, updated_at FROM jobs WHERE status = 'failed' ORDER BY updated_at DESC LIMIT 50;

- Requeue a job (pseudo):
  UPDATE jobs SET status='pending', attempts=0, next_attempt_at = NOW() WHERE id = '<job-id>';

- Trigger backfill (example script):
  scripts/backfill.sh --start 2026-07-01 --end 2026-07-15 --rate 50/s

Escalation

- Tier 1: on-call engineer (names/emails in CONTACTS.md)
- Tier 2: dev lead / system owner
- Tier 3: platform/infrastructure team

Post-incident

- Capture timeline, root cause, mitigation steps
- Create follow-up tasks (add to repo issues) for permanent fixes
- Update RUNBOOK.md with any new playbooks discovered during incident handling