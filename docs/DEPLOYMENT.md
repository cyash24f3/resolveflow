# Deployment

Live service: https://resolveflow-wojr.onrender.com

Render workspace: `cyash`; service: `srv-daugnmjncjis73fisc90`. Neon project: `bold-cake-51114732`, production branch: `br-shiny-tooth-b5pn8liz`. Both remain on their existing free plans. Secrets are managed outside Git.

## Release procedure

1. Run lint, formatting, type checks, the PostgreSQL regression suite and deterministic evaluation.
2. Test schema migrations on an isolated Neon child branch and verify that existing orders, proposals, approvals, effects and investigations are preserved.
3. Push the reviewed change and wait for GitHub Actions to pass.
4. Deploy the checked commit to the existing Render service. It pulls a public repository URL; automatic deployment is off.
5. Wait for the specific deployment to become live. Check `/api/v1/health`, `/api/v1/ready`, `/api/v1/config`, the browser console, and the complete public guest investigation/approval journey.
6. Verify a second visitor cannot access the first visitor's records. Record the deployed commit and real model used.

The hosted supervisor starts the migration process, then separate API and worker processes. An unexpected child exit fails the host so the platform can restart it. Workers stop claiming new jobs on SIGTERM; committed effects remain in PostgreSQL and unfinished deliveries can recover after lease expiry.

## Required settings

`REMOTE_DEPLOYMENT=true`, `DEMO_MODE=false`, `COOKIE_SECURE=true`, a TLS `DATABASE_URL`, distinct strong session/role secrets, and the provider settings from `render.yaml`. `PUBLIC_DEMO_ENABLED=true` enables isolated guest workspaces; it does not enable the loopback-only local demo endpoint.

Set `PROVIDER_API_KEY` to a key for a Google AI Studio free-tier project. The configured model preference is `gemini-3.8-flash`, followed by `gemini-3.6-flash` and `gemini-3.5-flash-lite`. Free quotas vary by account/model. Every actual provider call records its model; exhausted configured models produce a visible retryable failure. No paid model or fixture is automatically selected.

## Limits

A sleeping free instance does no work. It resumes queued work when the web service wakes. Free model quotas cannot provide an always-available inference guarantee. The workload is bounded and observable; it is not a production capacity SLA.

The original cloud deployment evidence in `docs/evidence/cloud-deployment.json` is historical. It describes the earlier scripted deployment and should not be confused with a verification of the current model-backed release.
