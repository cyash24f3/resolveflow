# Working API examples

OpenAPI is served at `/openapi.json`, Swagger at `/docs`, all application endpoints at `/api/v1`. JSON requests use bounded bodies and reject unknown fields. Successful requests include `X-Request-ID`; error envelopes include `request_id`, `error.code` and `error.message`. Pagination is bounded; event cursors are stable monotonically increasing IDs. No UI cookie contains a provider key.

Examples use local demo role login; remote deployments require `/auth/login` with the configured password. Replace placeholders manually, without committing passwords.

```sh
curl -c /tmp/rf-cookies -X POST http://localhost:8090/api/v1/auth/demo/operator
# Copy the csrf value from the JSON into CSRF locally.
export CSRF='CSRF_FROM_LOGIN'
curl -b /tmp/rf-cookies -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"customer_id":"C-100","message":"My lamp arrived damaged. Please replace it.","mode":"fixture","idempotency_key":"example-request-0001"}' \
  http://localhost:8090/api/v1/runs
curl -b /tmp/rf-cookies http://localhost:8090/api/v1/runs/RUN_ID
curl -b /tmp/rf-cookies -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"facts":{"order_id":"ORD-1001"},"idempotency_key":"example-clarify-0001"}' \
  http://localhost:8090/api/v1/runs/RUN_ID/clarification
# Once the run asks for damage evidence:
curl -b /tmp/rf-cookies -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"facts":{"damage_description":"Customer reports a crack","damage_reported_at":"2026-09-10T10:00:00+00:00","photo_reviewed":true},"idempotency_key":"example-clarify-0002"}' \
  http://localhost:8090/api/v1/runs/RUN_ID/clarification
# Switch to supervisor; copy the new csrf token into CSRF.
curl -c /tmp/rf-cookies -X POST http://localhost:8090/api/v1/auth/demo/supervisor
curl -b /tmp/rf-cookies http://localhost:8090/api/v1/proposals/PROPOSAL_ID
curl -b /tmp/rf-cookies -H "X-CSRF-Token: $CSRF" -H 'Content-Type: application/json' \
  -d '{"decision":"approve","expected_revision":1,"expected_hash":"EXACT_HASH_FROM_PROPOSAL"}' \
  http://localhost:8090/api/v1/proposals/PROPOSAL_ID/decision
curl -b /tmp/rf-cookies http://localhost:8090/api/v1/sandbox
```

An approval request contains no action amount or quantity. Those exist only in the persisted proposal. Same request key/payload returns the existing run; changed payload returns 409. Same clarification or approval decision retries return the existing result. Competing decisions have one transactional winner. Record-scope failures return indistinguishable 404 responses for unauthorized and nonexistent records.

Developer endpoints: `/runs/{id}/trace`, `/metrics`, `/evaluations`, and eligible `/runs/{id}/retry`. Operators can inspect concise observations and actual committed effects, not full protected traces. `/runs/{id}/cancel` prevents new effects once its lock wins. Health `/health` is liveness; `/ready` checks DB, checkpoint table and initialization; provider status is reported separately as disabled or configured-but-unverified.
