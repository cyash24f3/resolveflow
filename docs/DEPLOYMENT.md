# Deployment and free-cost boundary

## Cloud deployment: Render Free + Neon Free

The cloud target is a single **Free** Render Python web service backed by a separately provisioned **Free Plan** Neon PostgreSQL project. [`render.yaml`](../render.yaml) selects the free plan explicitly. It does not create a paid worker, disk or Render database. `resolveflow.hosted` initializes the schema, then supervises the API and a separate worker process. An unexpected child exit stops the other child and fails the host so the platform can restart it. SIGTERM stops new work and allows up to 125 seconds for the children to exit; Render is configured for 130 seconds. Hard stops still use the persistent queue, leases, checkpoints and operation ledger to recover.

As of 30 September 2026, Render's free web service sleeps after 15 minutes without inbound traffic and can take about a minute to wake. Its filesystem is ephemeral and its free PostgreSQL expires after 30 days; those are the reasons the deployment uses external Neon storage. The API and worker pause together while Render sleeps. A browser request wakes the service and queued work resumes after applicable leases expire. This is a portfolio deployment with sleep and quota limits, not an always-on service. See [Render Free](https://render.com/docs/free).

Neon's Free Plan currently includes 100 CU-hours and 0.5 GB of database storage per project. Keep the project on Free, use one primary compute with scale-to-zero, and place it near Render's region. Select a direct PostgreSQL connection string with TLS (the selected project is in AWS US East 2, matching Render Ohio). Worker polling keeps the compute active while the web service is awake; it is configured to five seconds to reduce database traffic. The worker is not a mechanism to avoid provider sleep or quotas. Monitor actual database compute/storage usage and host bandwidth/build usage. See [Neon's Free Plan](https://neon.com/blog/building-patterns-unlocked-by-scale-to-zero). Do not add a paid plan or payment method for this deployment; Render can charge overages on an account that has a payment method.

Deployment steps:

1. Connect Render and Neon through their integrations, using free accounts. Inspect existing resources and billing before creating anything; reuse a matching ResolveFlow project rather than creating duplicates.
2. Create the isolated Neon project/database, then obtain its **direct** connection URI with `sslmode=require` (or a stronger verification mode). Store it directly in Render's secret environment variable `DATABASE_URL`. Standard `postgres://` and `postgresql://` URIs are normalized to the installed psycopg driver. Never paste a connection URI into public GitHub files, issue comments, or browser URLs.
3. Create the Render Blueprint from `https://github.com/cyash24f3/resolveflow`, or create an equivalent Python **web service** with compute plan **Free**, Python 3.12.13, the Blueprint's environment values, build command `pip install uv==0.10.4 && uv sync --frozen --no-dev`, and start command `.venv/bin/python -m resolveflow.hosted`. Match the database region. Use health check `/api/v1/ready` and shutdown delay 130 seconds.
4. Generate four independent secrets for `SESSION_SECRET`, `OPERATOR_PASSWORD`, `SUPERVISOR_PASSWORD`, and `DEVELOPER_PASSWORD` (the Blueprint generates them). Keep `REMOTE_DEPLOYMENT=true`, `DEMO_MODE=false`, `COOKIE_SECURE=true`, and `PROVIDER_ENABLED=false` initially. Startup rejects weak/shared secrets, insecure cookies, local demo access, or a database without TLS.
5. Await successful build/deploy and record the platform-provided HTTPS URL. Verify readiness, the public read-only example, denied anonymous writes, credential login, operator scope, clarification, supervisor approval/rejection, and actual committed ledger state. Verify a restart against the same database. Only then mark remote deployment verified and add the actual URL to README and GitHub's About field.

An operator can sign in with the configured role password; share it privately with intended reviewers. Supervisor and developer passwords must remain private. The public example is a clearly labeled illustrative walkthrough; it neither creates a run nor displays private investigations. Optional live inference requires a separately supplied Groq Free Plan key stored as a host secret. It is disabled until verified, with no fixture fallback.

Cloud status: **accounts and target project confirmed; deployment in progress**. No cloud resource or public application URL has been created or verified yet. Local tests of the hosted process launcher do not establish Render, Neon or remote HTTPS success.

## Local containers

The tested path is local Docker Compose on Apple silicon, binding API and DB ports to loopback. API, worker and PostgreSQL run separately; migrations and checkpoint setup run once through the `migrate` service. A named `pgdata` volume persists all records/checkpoints. The image runs as UID 10001 and contains no `.env`, credentials, screenshots or local outputs.

```sh
uv run python scripts/bootstrap.py
docker compose up -d --build
curl http://localhost:8090/api/v1/ready
docker compose ps
docker compose restart worker
# Preserves the named volume:
docker compose down
docker compose up -d
```

For a remote environment you control, reuse the same image and database-backed queue. Supply secrets using the platform's secret store, run the documented migration job, keep a persistent PostgreSQL volume or configured managed PostgreSQL connection, and run one always-available worker initially. Disable demo access (`DEMO_MODE=false`), set unique role passwords, a random SESSION_SECRET, `COOKIE_SECURE=true`, and use HTTPS through a trusted reverse proxy. Publish only the API through that proxy; do not expose PostgreSQL. The proxy must set the correct source IP and host; never use the local-demo Host-header check as a remote security perimeter.

Remote accounts, HTTPS certificates, roles, volumes and worker lifecycle were not provisioned or verified. No always-on free cloud worker is promised. Avoid a sleeping free web process for durable worker claims; the DB survives sleep but investigations will wait. The requested cloud path is Render Free with Neon Free; the local stack remains available for development.

Validate readiness, credential login, operator scope, CSRF failures, supervisor decision, persisted effect, actual worker restart, read-only public mode, and DB volume survival before making a remote service available. `PUBLIC_READ_ONLY=true` blocks authenticated mutation routes; `/api/v1/sample` is a separate static fictional example, not a public private-run endpoint. Remove or gate `/docs` at the reverse proxy if desired; it contains schemas, not credentials.

Graceful termination stops new claims and lets the current bounded provider attempt finish. Stop grace period is 130 seconds; hard termination is reconciled after lease expiry. Back up the PostgreSQL volume using standard PostgreSQL tools. Keep backups private and apply your own backup retention, as the conversation-redaction CLI only covers the active database and checkpoints.
