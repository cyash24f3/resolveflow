# Evaluation

## Current v2 methodology

`data/sample/scenarios-v2.json` freezes 100 AI-authored synthetic episodes using seed 20261021. Seven whole categories (35 episodes) are development; thirteen whole categories (65 episodes) are test. No category crosses the split. This improves template separation but is still a small synthetic dataset, with no human-reviewed labels or production-distribution claim.

The evaluator supplies operator evidence, the request and observed clock. It no longer supplies the expected action through `run.facts`. Expected actions, outcomes and effect counts remain evaluator-only. The late-report category advances the clock beyond the report date and explicitly asserts DAM-02, so a future-date rejection cannot impersonate a window-boundary test.

Every episode gets fresh isolated records. Task completion checks the intended observable outcome, exact effect count/action/amount, scope, unique operations and named fault firing. `evaluation/oracle.py` separately checks the ledger against initial order state, cumulative monetary limits, damage evidence/windows, replacement restrictions and approval linkage. Policy-violation counts use this independent oracle rather than only checking that an approval exists.

Baseline and fixture are related scripted implementations, not independent AI competitors. Their comparison validates workflow consistency. Real provider checks are opt-in and bounded to five episodes; they establish integration behavior for the recorded model(s), not a robust intelligence ranking. Actual model names and free-model fallback events are recorded. Unknown usage remains unknown. Human semantic review remains pending.

## Evidence and historical results

Reports write to timestamped output directories and preserve failures. New runs are labeled regression executions. The v1 `scenarios.json` and existing `evaluation*.json` files are historical evidence from the earlier methodology, which reused categories across splits and supplied the expected action. They must not be presented as v2 or as live-model accuracy.

The first live integration sample exposed quota exhaustion and insufficient tool-validation feedback. These failures were used to improve provider scheduling, explicit free-model routing and argument repair. Later samples are exposed regression checks and should be described as such.

Latency is active graph processing, excluding human waits and harness setup. Provider scheduling/backoff is included. A localhost scripted latency is not an end-to-end hosted latency or an SLA. The historical 24-delivery contention experiment tests one operation's replay behavior, not independent-request throughput.

## Commands

```bash
uv run pytest -q
uv run python -m resolveflow.evaluation.runner --split ci --systems baseline fixture
uv run python -m resolveflow.evaluation.runner --split development --systems baseline
uv run python -m resolveflow.evaluation.runner --split test --systems baseline
uv run python -m resolveflow.evaluation.runner --split ci --systems provider --allow-live --limit 5
```

All database-backed checks require a PostgreSQL role with schema-creation permission. Live runs additionally need an explicitly enabled free/local provider. They never silently substitute a fixture.
