Troubleshooting — Common Issues & Diagnostics

1) Jobs stuck in pending or queued
- Symptoms: backlog grows, no inject requests leaving system
- Checks:
  - Orchestrator logs for scheduler errors
  - DB connectivity and locks
  - Leader election / distributed lock status
- Quick fixes:
  - Restart scheduler pod/process
  - Re-run migration if locking issue is due to schema mismatch

2) High job failure rate
- Symptoms: large percentage of jobs fail within a short window
- Checks:
  - Inspect error types in failures (5xx, timeouts, client errors)
  - Target system health (API changes, auth errors)
- Actions:
  - Pause backfills
  - Increase logging verbosity for a short window
  - Apply rate limiting or reduce injection rate

3) Collector not persisting results
- Symptoms: injections succeed but no results appear
- Checks:
  - Verify collector connectivity to object store/DB
  - Check parsing/normalization errors in collector logs
- Fixes:
  - Correct schema/parsing rules
  - Reprocess raw payloads if available (see EXAMPLES.md)

4) Auth/credentials errors
- Symptoms: 401/403 responses from targets, or DB auth failures
- Checks:
  - Validate secret rotation events
  - Confirm service account access
- Fixes:
  - Update secrets in secrets manager and restart services
  - Roll back recent credential rotations if needed

5) Performance degradation
- Symptoms: increased latency, DB slow queries
- Checks:
  - Slow query logs
  - Resource utilization (CPU/memory, disk I/O)
- Mitigations:
  - Add indexes for heavy queries
  - Scale out workers; batch writes

6) Data corruption or schema mismatch
- Symptoms: failed deserialization, migration errors
- Actions:
  - Restore from backup if critical
  - Run migration fix scripts and reprocess data

Diagnostic commands (examples)
- Tail orchestrator logs (k8s): kubectl logs -f deploy/orchestrator
- DB quick check: psql $DATABASE_URL -c "SELECT count(1) FROM jobs WHERE status='pending';"
- Broker lag (Kafka): kafka-consumer-groups.sh --bootstrap-server $BROKER --describe --group collectors

If uncertain, escalate per RUNBOOK.md escalation policy and collect logs, timestamps, and sample job IDs for triage.