# Implementation roadmap

| Phase | Deliverable | Acceptance |
|---|---|---|
| 0 | Standard-library core, deterministic demo, Windows/Linux environments | Unit tests and demo pass; no live-model claims |
| 1 | One instrumented tool environment and two cross-session tasks | Benign tasks work; actual model propagates allowed external content |
| 2 | Shared post-write checkpoints, detector interface, strong recovery baselines | Repair comparison uses identical state and alerts |
| 3 | Small RedTeamCUA GUI subset | Original grade preserved; all claimed protected sinks are mediated |
| 4 | Controlled evaluation and failure analysis | Reproducible raw records, uncertainty, costs and limitations |

Suggested workstreams: core/protocol, adapter/environment, attacks/evaluator,
research/statistics. Owners remain unassigned until the team agrees.

## First tasks

- P0-01: Pin upstream commits and licenses, run one original benign task.
- P0-02: Instrument observation and memory-write hooks with complete input IDs.
- P0-03: Implement exact dispatch binding and enumerate bypass paths.
- P0-04: Reset active context and cache after quarantine.
- P1-01: Build two synthetic-data tasks with live-model propagation.
- P1-02: Fork identical post-write checkpoints for recovery comparison.
- P1-03: Add clear-all, global-rollback, root-only and authority-repair baselines.
- P1-04: Validate a bounded GUI action surface.
- P2-01: Produce analysis scripts and reproducibility bundle.

No model budget, remote infrastructure, owner assignment or paper acceptance is
implied by this roadmap. Production hardening and general semantic repair remain
outside the current scaffold.
