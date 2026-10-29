Inject-Collect Project — Technical Handover

Executive summary

Inject-Collect is responsible for two complementary concerns:
1) injecting payloads/requests into target systems (injectors/adapters), and
2) collecting responses/results (collectors) and persisting them in storage for processing and analysis.

High-level architecture

- Orchestrator (scheduler): decides what to inject and when; maintains job state, retries, and backfill scheduling.
- Injectors (adapters): platform-specific components that perform injections (HTTP APIs, message brokers, devices). Each injector is an isolated adapter implementing a standard interface.
- Collectors: components that receive or poll for responses; normalize and persist events.
- Persistence: database(s) for job metadata and results (Postgres or equivalent), object storage for large payloads (S3-compatible), and a message broker for decoupling (Kafka/RabbitMQ optional).
- Observability: metrics, logs, traces (Prometheus/Grafana + structured logs + optional distributed tracing).

Core data model (conceptual)

- Job
  - id
  - type (scheduled, adhoc, backfill)
  - payload reference (pointer to stored payload)
  - status (pending, running, success, failed)
  - attempts, next_attempt_at
  - created_at, updated_at

- Result/Event
  - id
  - job_id
  - status
  - response_payload (or storage pointer)
  - received_at
  - metadata (latency, target, http_status)

APIs and interfaces

- Internal orchestrator API (gRPC/HTTP) exposes:
  - CreateJob(payload, schedule)
  - GetJob(job_id)
  - ListJobs(filtering)
  - AcknowledgeResult(result_id)

- Injector interface (pseudo-signature):
  - send(payload) -> (success/failure, metadata)
  - status() -> health

- Collector interface:
  - ingest(raw_event) -> normalized Event
  - poll() -> batch

Configuration

- config/*.yaml or config/*.json stores runtime configs (adapters, connection strings, retry policy, rate limits).
- Secrets should not be checked into git; use a secrets manager (Vault, AWS Secrets Manager). Document secret names and access in CONTACTS.md.
- Environment variables: Provide .env.example with required variables. Key env vars:
  - DATABASE_URL
  - OBJECT_STORE_URL
  - BROKER_URL
  - LOG_LEVEL
  - SERVICE_PORT

Deployment & CI/CD

- Container images: each component should have a Dockerfile. Images are built and pushed in CI (scripts/ci or .github/workflows).
- Deployment: Kubernetes manifests or deployment scripts live in k8s/ or deploy/. Use templating (Helm, kustomize) for environment differences.
- Migrations: use a migration tool (e.g., Flyway, Alembic, Liquibase)—store migration scripts under db/migrations.

Observability & SLOs

- Metrics to expose:
  - jobs_scheduled_total
  - jobs_failed_total
  - job_processing_latency_seconds (histogram)
  - injector_errors_total{injector}
- Logs: structured JSON logs including job_id and trace_id. Ensure sensitive data is redacted.
- Alerts:
  - Job failure rate > X% over 5m
  - Consumer lag (if using Kafka) > threshold
  - DB connection errors

Operational flows

1. Normal injection flow
  - Orchestrator schedules job → payload stored → injector picks up job → sends to target → returns status → collector ingests and persists result.
2. Retry/backoff
  - On transient failures, orchestrator reschedules with exponential backoff. Ensure injectors implement idempotency keys if targets require them.
3. Backfill
  - Backfill tool replays payloads via a separate backfill worker, using bulk job creation APIs and rate limiting to avoid target overload.

Security

- Principle of least privilege for service accounts.
- Store credentials in a secrets manager; rotate keys periodically.
- Use network policies and TLS for service-to-service communication.

Testing

- Unit tests for business logic and adapters (mock external calls).
- Integration tests with local emulators (localstack for S3, dockerized Postgres, RabbitMQ).
- End-to-end smoke tests under examples/ to validate full pipeline.

Performance & scaling

- Scale orchestrator horizontally; use leader election or a distributed lock for single-leader responsibilities (e.g., scheduling cutover).
- Injectors/collectors scale independently based on throughput.
- Use batching in collectors to improve DB write efficiency.

Extensibility

- New adapter pattern: implement the injector/collector interface and register in config.
- Keep adapters small and focused; prefer composition over monolith.

Files & locations (update if repo structure differs)

- src/                 — orchestrator and adapters
- src/orchestrator/*    — core scheduler and job management
- src/adapters/*        — injector & collector implementations
- config/               — runtime configs
- scripts/              — local helpers, start/stop, backfill
- examples/             — sample payloads and test configs
- docs/                 — diagrams and additional docs
- db/migrations/        — schema migrations

TODOs (environment-specific)
- Replace TODO placeholders with concrete runtime and secret names.
- Fill exact DB schema and API contract examples.

Contact and ownership info should be filled in CONTACTS.md.