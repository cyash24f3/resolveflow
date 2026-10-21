# Release verification

Verification date: 21 October 2026. The hardening release is application version **0.2.0**, runtime commit `1bd0015610cf18403a715a3e9a327fecaa3d3bf3`.

## Current checks

| Check | Observed result | Evidence |
| --- | --- | --- |
| Frozen install, lint, formatting, typing and JavaScript syntax | Passed in GitHub Actions | [Release CI](https://github.com/cyash24f3/resolveflow/actions/runs/39619487289) |
| PostgreSQL regression tests | 84 passed | Release CI; approval/clarification races, cumulative refunds, evidence binding, identities, isolation and recovery regressions |
| Deterministic v2 evaluation | 100/100 baseline episodes; zero observed policy violations | [evaluation-v2.json](evidence/evaluation-v2.json) |
| Commit-before-checkpoint recovery | Separate process exited 77; recovery retained exactly one business effect | [recovery.json](evidence/recovery.json); release CI |
| Migration on existing cloud data | Revision 003 applied on an isolated Neon child branch; original orders, effects, proposals, approvals and runs preserved | [Release verification report](evidence/release-20261021.json) |
| Public cloud release | Render deployment `dep-dbccvj1srm7s738d3800` became live; HTTPS health/config/readiness returned successfully | [Release verification report](evidence/release-20261021.json) |
| Public browser workflow | Real AI cancellation approved: one effect; baseline refund rejected: zero effects; visitor isolation, mobile overflow and browser console checks passed | [Release verification report](evidence/release-20261021.json) |

The deterministic evaluation is an exposed regression check on AI-authored synthetic data. It measures the baseline and business guards, not live model accuracy. Human semantic review remains pending. The real-provider checks are bounded integration exercises and do not establish a statistical quality score.

## Scope of the guarantees

The protected business effects are fictional PostgreSQL records. Approval, freshness checks, operation deduplication, order updates, the ledger and audit writes share the database transaction boundary. External payment or shipment systems would need their own idempotency and reconciliation.

Real model availability depends on the provider's free quotas. The preferred model and configured free fallbacks are distinct from the explicitly selected baseline/fixture modes. The app does not silently substitute a scripted result for an unavailable model. Free Render hosting can sleep when idle.

## Historical evidence

Earlier evidence remains in `docs/evidence/` rather than being relabeled as current:

- `clean-checkout.json`, `tests.txt`, `github-ci.json` and `github-cloud-ci.json` describe earlier 41/56-test releases.
- `evaluation-development.json`, `evaluation-test.json` and `episodes-*.jsonl.gz` use the older v1 synthetic dataset. They are not the category-disjoint v2 evaluation.
- `concurrency-failure.json` retains the original concurrency failure.
- `live-integration-before-hardening.json` retains the first bounded real-provider failures.
- `browser.json`, the older screenshots, `cloud-deployment.json`, `containers.json`, `hosted-container.json` and `load.json` describe earlier scripted deployments and local experiments.

No production capacity, human semantic quality score, real image inspection, financial transfer or external shipment is claimed.
