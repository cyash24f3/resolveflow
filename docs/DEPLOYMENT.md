# Deployment and free-cost boundary

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

Remote accounts, HTTPS certificates, roles, volumes and worker lifecycle were not provisioned or verified. No always-on free cloud worker is promised. Avoid a sleeping free web process for durable worker claims; the DB survives sleep but investigations will wait. The chosen default is local hosting to honor the user's free-only constraint.

Validate readiness, credential login, operator scope, CSRF failures, supervisor decision, persisted effect, actual worker restart, read-only public mode, and DB volume survival before making a remote service available. `PUBLIC_READ_ONLY=true` blocks authenticated mutation routes; `/api/v1/sample` is a separate static fictional example, not a public private-run endpoint. Remove or gate `/docs` at the reverse proxy if desired; it contains schemas, not credentials.

Graceful termination stops new claims and lets the current bounded provider attempt finish. Stop grace period is 130 seconds; hard termination is reconciled after lease expiry. Back up the PostgreSQL volume using standard PostgreSQL tools. Keep backups private and apply your own backup retention, as the conversation-redaction CLI only covers the active database and checkpoints.
