# Acceptance checklist

Verification date: 30 September 2026. Evidence is from actual local execution; no live-provider, remote-deployment or human-review success is invented.

| Criterion | Status | Evidence |
|---|---|---|
| 1. Clean checkout starts and seeds fictional records | Pending final clean-checkout check | `scripts/bootstrap.py`, `resolveflow.cli init`; final clean-checkout evidence will be saved below |
| 2. Fixture and fixed workflow need no paid credentials and have distinct labels | Verified | `tests/test_workflows.py`, `evaluation-development.json`, `evaluation-test.json`, current `evaluation-ci.json` |
| 3. Real model chooses tools in a verified investigation | Implemented, unverified | `agent/providers.py`, mocked `test_provider_adapter.py`; no free-tier key or installed local model was supplied |
| 4. Missing facts pause and resume | Verified | `tests/test_api.py`, actual `browser.json`, `requests-awaiting-approval.png` |
| 5. Exact proposal approval and rejection by permitted roles | Verified | `test_approval_queue.py`, `test_api.py`, browser supervisor journey |
| 6. Unapproved/out-of-scope/expired/stale effects blocked | Verified | Approval, scope, stale-order, expiry tests; frozen scenario traces |
| 7. Duplicate/concurrent delivery produces unique effects | Verified after repair | `concurrency-failure.json` retains the original failure; current concurrency regression and `load.json` |
| 8. Actual restart recovers commit-before-checkpoint | Verified | `scripts/recovery_demo.py`, `recovery.json`: exit 77 followed by another process, one effect before/after |
| 9. Interface exposes policy sources and actual committed state | Verified | Actual Chromium screenshots and `browser.json`; Jinja + DOM escaping + protected API data |
| 10. Frozen comparison, denominators and failure evidence | Verified for fixture/baseline; live comparison unverified | 100 families, 35/65 split, `episodes-*.jsonl.gz`, reports, retained concurrency failure, blank semantic review CSVs |
| 11. Containers persist business records and checkpoints | Containers running; final restart check pending | Compose named volume, non-root UID 10001, readiness and image checks |
| 12. Injection, timeout and unsafe calls have observed outcomes | Verified for deterministic guards and mocked provider failures | Tool/scope tests, `test_provider_adapter.py`, named read-timeout scenarios and episode exports |

Primary commands actually run: `uv sync --python 3.12`, migrations/seed + PostgresSaver setup, Ruff, mypy, pytest, development/test/CI evaluations, Chromium browser checks, actual separate-process restart, 24-delivery/eight-thread load, Docker build and Compose startup. Current `tests.txt` records the final suite count. Tests use real PostgreSQL; protocol/error tests use explicitly mocked model outputs.

The first 200 synthetic episodes predate the concurrency repair and subsequent domain/checkpoint hardening. They are preserved honestly as historical outputs. The current CI regression subset includes exposed families and is not a new holdout. No model prompt was tuned on held-out successes. No human semantic labels have been filled.

No remote environment, GitHub-hosted CI run, production capacity, real attachment inspection, real financial effect, model quality score or paid service was verified. The complete credential-free sandbox is the core delivery. Follow `FREE_TIERS.md` to configure a bounded real-provider sample separately.
