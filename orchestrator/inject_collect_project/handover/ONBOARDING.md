Onboarding — Development & Local Setup

Purpose

Step-by-step guide for new developers to get a local development environment and run a minimal end-to-end flow.

Prerequisites (examples — update to match repo)

- Git
- Docker & Docker Compose (for local emulators)
- Language runtime: specify (e.g., Python 3.11 or Node 18)
- postgres locally or via docker-compose

Steps

1. Clone the repo
  git clone <repo-url>
  cd orchestrator/inject_collect_project

2. Copy example env and populate secrets
  cp config/.env.example .env
  # Fill in DB, object store and broker endpoints. Use local docker endpoints for testing.

3. Start local dependencies (docker-compose)
  docker-compose -f docker/docker-compose.local.yml up -d
  # Wait for Postgres and any broker to be ready

4. Install deps & run migrations
  # Python example
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -r requirements.txt
  alembic upgrade head

  # Node example
  npm ci
  npm run migrate

5. Start services locally
  scripts/start-local.sh
  # Or run individual components with DEBUG logging

6. Run a sample injection (from examples/)
  scripts/run-sample.sh examples/sample-payload.json
  # Verify result via DB query or examples consumer

7. Run automated tests
  scripts/test.sh

Development notes

- Adapter pattern: add new injector under src/adapters/<name> and register in config.
- Use feature branches and open PRs. Follow repository CONTRIBUTING.md (if present).

Troubleshooting local setup

- If migrations fail, ensure DB is reachable and .env values are correct.
- If a service fails to start, inspect logs under logs/ or run with DEBUG=debug.

Keep ONBOARDING.md updated with exact runtime and scripts used in this repo.