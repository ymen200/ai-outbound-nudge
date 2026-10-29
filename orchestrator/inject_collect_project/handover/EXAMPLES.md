Examples — Quick sample workflows and configs

This file contains runnable examples to validate the end-to-end pipeline locally.

Sample payload (examples/sample-payload.json)
{
  "job_type": "ping",
  "target": "https://example-target.local/api/ping",
  "payload": {"id":"sample-123","data":"hello"}
}

Sample run (script)
- Run the sample via script: scripts/run-sample.sh examples/sample-payload.json
- Expected flow: job created → injector sends payload → collector stores result in DB

Sample SQL queries
- Latest results:
  SELECT * FROM results ORDER BY received_at DESC LIMIT 20;

- Failed jobs last 24h:
  SELECT id, error_message, updated_at FROM jobs WHERE status='failed' AND updated_at > NOW() - INTERVAL '24 hours';

Example config snippet (config/injector.yaml)
retry_policy:
  max_attempts: 5
  backoff_seconds: 10
rate_limit:
  requests_per_second: 50

Notes
- Replace sample endpoints with local docker-compose endpoints when testing.
- Add more sample payloads for each adapter type (HTTP, queue, device) to exercises adapters.