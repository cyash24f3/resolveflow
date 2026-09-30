# Fictional business policy, contract v1

Every effect is simulated. INR values use paise (integer minor units). No real payment, shipment, email, or ticket service is connected.

Policy is selected by **purchase date**, using half-open [effective_from, effective_until) intervals, for damage, delay and cancellation. No matching version or overlapping versions requires escalation. Version IDs and source hashes are preserved in every eligibility observation and proposal. The damage window is measured from verified delivery to the **operator-recorded report timestamp**, not from purchase or today's date. Negative intervals and conflicting tracking records require escalation.

- DAM-01: Damage resolution requires a delivered order, reported damage description, report timestamp, and operator attestation that a sandbox photo was reviewed. A customer statement alone is unverified. This is a fictional evidence rule, not automated image inspection.
- DAM-02: Version 2025 permits reports within 14 days; version 2026 within 30 days, inclusive. Resellers are excluded from damage refund and replacement (RES-01).
- REF-01: Refunds must be positive, match currency, and be at most paid item+shipping total minus previous refunds. Partial prior refunds do not authorize a replacement for fully compensated goods; any prior refund blocks replacement under REP-02.
- REP-01: One replacement cycle per order, quantity at most purchased quantity, no prior replacement. No replacement after a full refund or cancellation.
- CAN-01: Unshipped, uncancelled, unrefunded orders may be cancelled. Cancellation changes state only: it does not implicitly refund money. A cancellation requires supervisor approval.
- DEL-01: If undelivered and at least seven days past the promised date, a shipping-fee refund (up to remaining refundable total) may be proposed. Delivered late orders require escalation rather than an automatic delay refund.
- CON-01: Tracking delivery conflicting with order delivery, future report times, unavailable policy coverage, or unresolved facts escalate or pause. Unknown categories escalate.
- APR-01: Refund, replacement and cancellation require an exact, unexpired supervisor decision bound to immutable payload hash, workspace and revisions. Approval lasts at most 24 hours and cannot change these rules. Relevant order revisions are checked again at execution.
- IDEM-01: Same operation and payload returns the committed record; changed payload conflicts. Two separate requests are not deduplicated as transport retries, and still contend on the order lock.
