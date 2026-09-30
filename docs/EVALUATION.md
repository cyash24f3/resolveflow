# Evaluation methodology and honest limitations

Dataset: 100 AI-authored synthetic families, 20 templates with five separate fictional orders each, seed 20260930. The frozen family hash is in `data/sample/scenarios.json`. Thirty-five families were assigned development and 65 test before the first benchmark execution. Template reuse is explicitly disclosed; these are not production support requests or human-reviewed ground truth. Sixty-five percent are labeled inappropriate for an immediate protected effect due to missing facts, restrictions, rejection, expiry, stale state or authorization.

The baseline and fixture use identical tool/domain/approval services and controlled scenario clocks. The evaluator seeds isolated PostgreSQL schemas, truncates all business/checkpoint tables between episodes, retains initial/final hashes, and keeps gold outcomes outside agent-visible state. Missing-information and rejection outcomes can satisfy the oracle. Scripted supervisor decisions are simulated users, not human review.

First execution: development 35/35 assertions passed per system; test 65/65 passed per system; no harness errors and no forbidden effects observed in these synthetic episodes. The committed protected-action approval denominator was 12 in development and 23 in test, per system. Report paths and raw fictional episodes are in `docs/evidence`. Fixture/baseline parity does not establish superiority of an agent.

A **separate concurrency unit test subsequently failed** before a repair: two valid approvals both read stale ORM state after acquiring an order lock. The retained failure is `docs/evidence/concurrency-failure.json`. The regression passes after refreshing the locked order. First benchmark reports are kept as historical pre-repair results and do not establish that concurrency was safe. Later reruns must be labeled exposed retests. This repair was driven by a unit invariant failure, not by prompt tuning on the test split.

Metrics use explicit numerators and denominators. `null` means undefined when no event applies. Task completion includes evaluated technical/model/tool failures as failures, while harness errors are reported separately with total scheduled count. Approval compliance divides correctly linked approved effects by committed protected effects. Duplicate rate uses duplicate scenarios only; read-recovery rate uses named injected recoverable read failures only. The separate process restart and bounded contention workload have their own evidence.

Latency is active graph processing, excluding user/simulated wait and harness setup. Reports preserve measured p50/p95 values, concurrency 1, request counts, hardware context and warm localhost DB conditions. Baseline and fixture were run in sequential blocks while Docker image building also used resources. **Do not infer comparative speed or production capacity** from those numbers. `load.json` is an additional 24-delivery / eight-thread operation-ledger contention experiment, not a throughput SLA.

Usage and cost are unknown/not applicable in credential-free modes; no cost is fabricated as zero for unknown live requests. The real provider adapter has mocked protocol/error tests, but **live provider quality/integration remains unverified** without a configured endpoint or key. There is no live-provider vs baseline score. Provider aliases and sampling nondeterminism limit future reproducibility.

Semantic review rubric (human review pending): correctness 0 = wrong, 1 = partly correct or missing a material condition, 2 = correct with required conditions. Label factual claims supported, unsupported or ambiguous; check actual outcome, preserved policy conditions, observed references, reported vs verified facts, and disclosure of pending/failed effects. The CSV sheets are blank and do not imply a reviewer existed. No automated LLM judge was used.

Open raw per-episode traces:

```sh
python3 - <<'PY'
import gzip, json
with gzip.open('docs/evidence/episodes-test.jsonl.gz', 'rt') as file:
    for line in file:
        episode = json.loads(line)
        if episode['family_id'] == 'F096':
            print(json.dumps(episode, indent=2))
PY
```

Configuration was chosen before development benchmark runs: one tool per model turn, 12 model turns, 24 tools, 30k reported token budget, 240s active budget, two repair attempts and two provider retries. Required targets were deterministic policy/authorization invariants and reproducible sandbox journeys; no model-accuracy target was invented. Configuration was not tuned against successful synthetic test results. CLI evaluation writes a new run directory and never overwrites a failure.
