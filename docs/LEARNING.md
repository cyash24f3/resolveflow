# Learning guide and interview walkthrough

1. Read `docs/POLICY.md`, then `domain/policy.py`. Explain why a model cannot increase the refund cap, ignore a reseller restriction, or treat a customer's text as verified evidence.
2. Read `tools/contracts.py` and `tools/executor.py`. Inspect a real `/runs/{id}` response. Trace one observation ID through policy version, eligibility and exact proposal.
3. Compare `Baseline`, `Fixture` and `Provider` in `agent/providers.py`. Identify where the live model genuinely selects a tool, and where the default fixture scripts decisions. Explain why fixture accuracy cannot establish model reasoning quality.
4. Follow `agent/workflow.py`: bounded step → typed observations → interrupt for information/approval → separate protected action → server-grounded outcome. An interrupt replays its containing node, so writes cannot rely on node placement alone for uniqueness.
5. Study `approvals/service.py` and `jobs/queue.py`. Write down the unique keys and lock order. Explain why a reused request key with different content must conflict. Explain why two different customer requests still need order-level contention.
6. Run the separate-process recovery demo. Locate the ledger commit and missing graph checkpoint. Describe how a new worker discovers the original effect after lease expiry.
7. Read the retained concurrency failure. A row lock alone did not refresh the SQLAlchemy identity map. Explain why database transactions and ORM object state both matter, then run the regression test.
8. Read the frozen scenario families and exported traces. Verify the denominator for a waiting outcome, an approval rejection, no committed protected effects, and a harness error. Fill a semantic-review row yourself; do not relabel automated tests as human review.
9. Configure a local or free provider and run one explicitly bounded live episode. Record returned model alias, usage, failures, source references and exact final database state. Preserve failures before changing prompts. Avoid tuning on exposed test families and calling them held out again.
10. Demonstrate the UI to an interviewer: submit → missing facts → cited policy → exact proposal → supervisor → committed simulated state. Show operator approval denial, stale-record rejection, cancellation boundary, and recovery evidence.

Design choices: one worker loop and modular monolith keep the project maintainable. PostgreSQL holds both business records and persistent checkpoints; they still use different transaction boundaries. Plain HTML/CSS/JS keeps the UI inspectable without a frontend build service. Money is integer minor units. No vector database is needed for the small bounded versioned policy corpus. No paid monitoring platform is needed for persisted structured events.

Future work, after core validation: real model comparison, manually reviewed response rubric, randomized controlled timing runs, attachments, multiple-item orders, per-user role assignments, HTTP sandbox adapters with unknown-outcome reconciliation, and optional read-only public presentation. None is required for the credential-free core.
