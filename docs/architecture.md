# Architecture decision: host library first

The initial artifact is a single-process Python library with a SQLite ledger.
The ledger, input capture and exact action capabilities belong to a trusted host.
The agent must not construct capabilities or edit the ledger in a real deployment.

The implementation separates observed origin from authorization. External data
may be used within an independent task capability; text never grants capability.
An inline envelope is checked against the host ledger, including content digest,
version and current status. Missing captured parents produce unknown origin.

Repair starts with a call ID and independently confirmed roots. The planner finds
captured ancestors, then quarantines confirmed roots and their descendant closure.
Rebuilding appends a new version from active inputs; it never promotes the origin
of a sanitized external source. Unrelated branches remain active. The old version
stays in the audit record and cannot pass retrieval verification.

This graph over-approximates input dependency; it does not establish semantic or
causal responsibility. A mixed benign/poisoned summary is quarantined as a whole.
The present demo supplies oracle roots and clean rebuilt content explicitly.

## Pending integration obligations

- Capture every actual model input and every memory transformation outside model control.
- Intercept every protected execution route, including native GUI alternatives.
- Bind actual bytes, resource and recipient at execution time; handle TOCTOU.
- Reset polluted active context and caches before continuation.
- Record real execution outcomes separately from pre-dispatch decisions.
- Add process/OS isolation before claiming tamper resistance.
- Define distributed transaction, retry and external side-effect semantics.

The core is intentionally not a universal CUA security boundary. See the research
documents for the full threat model, existing prior art and experiment protocol.
