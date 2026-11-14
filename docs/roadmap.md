# Implementation roadmap — reuse first

Updated 2026-11-01 following the project owner's direction. Prefer available original implementations over our minimal core. Keep the old core as a mechanism baseline while upstream components are qualified. Use desktop ChatGPT first; paid API experiments are currently disabled.

| Phase | Deliverable | Acceptance |
|---|---|---|
| 1 | Integrate reviewed upstream label, provenance, authorization and detection/recovery components | Author/reimplementation identity, license, commit and dependencies recorded; actual upstream checks and adapters validated |
| 2 | Add RedTeamCUA and lightweight tool benchmarks | Original benign tasks/scorers work; active attacks; equivalent policies and shared contamination checkpoints |
| 3 | Local desktop ChatGPT integration and real-scenario validation | Supported hook/MCP paths covered; checks before effects and result admission; failure/bypass behavior documented |
| 4 | Measured upstream patches and contribution candidates | Reproducible counterexamples, original-vs-patched comparisons, utility/regression checks and prior-art review |

Suggested workstreams: core/protocol, adapter/environment, attacks/evaluator,
research/statistics. Owners remain unassigned until the team agrees.

## First tasks

- P0-01: Pin source identity, license and revision; run original offline checks before modification.
- P0-02: Qualify OpenAPPA and TMA-NM adapters; preserve actual sanitizer failures and stand-in distinctions.
- P0-03: Confirm AgentSentry reuse terms and required replay/model interfaces; locate original MemLineage/ChronoMem artifacts.
- P0-04: Map labels, provenance, revocation, state and effects explicitly. Do not merge incompatible policy semantics by weakening them.
- P1-01: Run benign and attack tasks through the original benchmark scorers.
- P1-02: Fork identical post-write checkpoints for recovery comparisons with strong baselines.
- P1-03: Qualify desktop hook/tool coverage, timeout behavior and context ownership before installing a protection layer.
- P2-01: Produce independently checkable results and then evaluate patches and novelty.

## Current qualification status

Eight source checkouts are locked in `upstream-reuse-lock.json`. The original TMA-NM scope gate and recovery catalog are actually invoked by `scripts/demo_reused_authority.py`. OpenAPPA native Windows policy replay works, while actual email-redactor integration still has an unresolved failure. This is a first integration slice, not a completed unified defense.

One integration repository may manage separate environments/sidecars. Existing self-written modules are historical baselines, not silent fallbacks mislabeled as upstream implementations. See `upstream-reuse.md`.

## Novelty remains hypothetical

Compare inline-only, ledger-only and two-copy labels under loss, tampering and version drift. Two mutable copies within one trust domain do not create an independent security boundary. Compare graph-local repair with original upstream recovery, root-only deletion, global rollback and clear-all under identical detection and authorization conditions. Measure benign retention, task continuation, recurrence and incomplete dependency capture before claiming precision or novelty.

No paid-model budget, remote infrastructure, owner assignment, public license or paper acceptance is implied. Large resources stay on D:; personal files/apps are not automatically removed or terminated. Full benchmark deployment, desktop integration and persistent semantic recovery remain pending.
