Contacts & Access — Owners, Escalation, Credentials

Owner & Maintainers
- Project owner: <NAME> — email: owner@example.com
- Dev lead: <NAME> — email: devlead@example.com
- SRE on-call: <NAME> — pager: +1-555-555-0100

Escalation matrix
- Triage (first 15 min): on-call engineer
- 15-60 min: Dev lead
- 60+ min: Platform/infra team

Credentials & Secrets
- Secrets manager: Vault (path: secret/data/inject-collect) — TODO: verify path
- CI/CD deploy key: stored in CI project secrets (e.g. GitHub Actions secrets)
- DB credentials: stored in Vault; never commit to git

Access
- Dashboards: <Grafana URL> (update)
- Logs: <ELK/Cloud logs URL> (update)
- Runbooks & incident channel: #oncall-inject-collect

Please fill concrete names, emails, and credential locations during handover.