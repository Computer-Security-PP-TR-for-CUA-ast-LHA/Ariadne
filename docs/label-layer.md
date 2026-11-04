# Persistent label and version authority (local integration draft)

## Integration status against recovery v0.2 (2026-11-04)

This local branch starts from `main` commit
`aea1a7079eaea789a972b3545d0cc95b8d6f232f`. AgentLAB and RedTeamCUA
entry points now instantiate `PersistentLabelStore`, `LabelRecoveryBridge` and
`LabelSession`; legacy `GuardedSession` remains for its historical tests. The
team lead selected this layer as the authority for version identity, committed
status and scope revision. The bridge projects normal writes to recovery,
replays an interrupted projection from the mirrored outbox, and blocks all
managed reads/actions while a projection or repair is incomplete. Recovery's
SQLite version rows and revision are fenced working copies, never an alternate
permission source. Recovery publication installs the manifest in both label
files before context ACK.

The agreed ownership boundary is: the label files hold committed content,
labels, version identity, status and revision; `recovery/sqlite.py` holds repair
plans, staged candidates, effect records, context and the recovery barrier.
They are separate databases, so the cross-component workflow is an
acknowledged fail-closed saga rather than a single distributed transaction.
The graph group can consume
`export_graph_handoff()` (`scope_id`, `ledger_revision`, versions, host events,
repair mapping), or supply a `GraphPort` to the recovery coordinator. The other
modules still need to adopt the concrete API below during integration.

## Authority and repair protocol

| Operation | Caller and input | Committed result |
|---|---|---|
| Normal write | Host adapter calls `LabelRecoveryBridge.capture(session_id, artifact, content, parents, ...)` | The two label files commit the new version and revision first. The recovery working copy then appends the same version. A projection gap blocks all managed reads/actions and can be replayed from the mirrored outbox. |
| Isolation | Recovery coordinator supplies a graph plan with `scope_id`, base `revision`, target version IDs and request ID. `LabelOwnedRecoveryStore.quarantine()` calls `PersistentLabelStore.quarantine_repair()` after preparing the fenced working copy. | Both label files commit `quarantined` for exactly those IDs at `base revision + 1`. A crash between working-copy update and label commit is replayed from the durable recovery job; the barrier stays closed. |
| Candidate repair | Recovery backend supplies new content and validation evidence. | Candidates remain staged in recovery and are not visible as active label versions. |
| Publication | Recovery supplies a full manifest and old-to-new mapping through `LabelRepairProjection.install()`. | The label service validates and commits old/new status, replacement content and `revision` in both files. It checks the recovery working copy against the committed label snapshot, including dependency and audit edges, before context ACK. |
| Resume | Host calls `LabelRecoveryBridge.assert_ready()` before messages, action authorization or graph export. | Only a released recovery barrier, equal revisions and matching versions/edges permit use. A repaired action is replanned and authorized again. |

The recovery implementation currently writes its own working copy before each
label commit while the scope is fenced. That ordering supports idempotent
replay; it does **not** make its copy authoritative. If any step fails, the
scope stays blocked until the committed label state and working copy match.
This authority boundary applies to the integrated `LabelOwnedRecoveryStore`
port; direct use of the generic `SQLiteRecoveryStore` demo is outside it.

The integrated AgentLAB Email smoke uses the actual pinned environment and
tool schema with a scripted model and fixture checks. It is not an official
benchmark score, live-model result or RedTeamCUA VM validation.

This draft is local. It has not been pushed to the team repository. It defines
the interface for the member responsible for persistent labels and the separate
second label database. The existing `store.py` demo is a reference for artifact
IDs and graph handoff, not the implementation or evaluation baseline.

## Source and scope

- FIDES: [paper](https://arxiv.org/abs/2505.23643), [maintained Agent Framework implementation](https://github.com/microsoft/agent-framework/blob/b7884ad88eb85c27b2a7bf40c0e15948e7ccc28d/python/packages/core/agent_framework/security.py), MIT. `label_store.py` adapts the integrity/confidentiality restrictive join and serialization idea. The original module is saved locally at `project/third_party/fides-source/security.py` with its license. This is a **small adapted subset**, not the complete FIDES middleware.
- TMA-NM: [paper](https://arxiv.org/abs/2606.24322), [author artifact](https://github.com/yedidel/mem-inv-bench/tree/cf3c9a4ca9f0478000d6aa26eb268b875232d34b), MIT. The **actual upstream `tma.py` code** is vendored at `src/cua_guard/vendor/tma.py` with its license. `source_auth.py` calls its authenticated channel registry and origin-to-authority mapping. The original experimental monitor is in memory, so the two-file persistence layer is Ariadne-specific. Upstream `python code/test_tma.py` passed locally.
- PPMF: [paper](https://arxiv.org/abs/2607.29167). Its platform-maintained provenance and action-risk boundary motivate the persistent label design. No verified upstream implementation has been imported; this is not called PPMF code reuse.
- SAGE-Mem: [repository](https://github.com/AGAMPANDEYY/sage-mem/tree/fdd5c24c049bd3b0949d2cf87d18179f57712222), MIT. Its `MemoryItem` tracks `source_type`, `parent_ids`, `trust`, `claimed_source` and other fields; the full stack adds torch, embeddings and model-related dependencies. It is a potential write-time guard supplement, not the chosen deterministic tag database.
- CaMeL: [repository](https://github.com/google-research/camel-prompt-injection/tree/f083b6b396399d3b3c7f2ddaf613a5945eaf32d8), Apache-2.0. Useful for protected execution design, but its interpreter is not a drop-in persistent memory store.

## Data contract

`PersistentLabelStore` owns two distinct SQLite files. The primary file stores
content and a label; the mirror stores only `id`, scope, artifact/version,
content hash, label, status, parent IDs, producer and creation revision. Both
files also hold a scope revision and host event outbox. A trusted harness passes observed source
channels and actual model inputs. The model and external documents cannot set
source, principals or authorization.

| Field | Meaning | Owner |
|---|---|---|
| `id` | Stable UUID for one version | label store |
| `scope_id`, `created_revision` | Managed state scope and commit watermark | label store |
| `artifact`, `version` | Logical memory object and monotonic version | label store |
| `content_hash` | SHA-256 over UTF-8 content, equal in both copies | label store |
| `origins` | Observed entry channels: user/external/tool/model/unknown | trusted harness |
| `domains`, `authority` | TMA-NM administrative domains and NONE/INFORM/ACT class | authenticated registry / label join |
| `integrity` | Trusted only for directly host-attributed user content or approved host transforms of trusted input | label join |
| `confidentiality`, `principals` | FIDES-style read/sink restriction; identity label requires named principals | trusted harness and label join |
| `parents`, `producer` | Captured source IDs and host/model transformation kind | trusted harness |
| `status` | Active, quarantined, staged or superseded; status is mirrored | label store / repair controller |

The graph member can consume `export_graph_handoff()` and the recovery
`GraphPort` contract. The repair coordinator proposes a new version and an
old-to-new mapping; only label publication makes them authoritative. No old
quarantined version is made active. Dependency edges establish captured input
flow, not semantic causation.

## Security and write protocol

`join_labels` follows the restrictive FIDES ordering: any untrusted input makes
the result untrusted, and confidentiality only gets stricter. `derive` defaults
to a model-produced transformation, so even a user-only model summary is
untrusted and its action-authority class is at most INFORM. A host-only deterministic transform must be explicitly marked
`producer="host"` by the harness. Missing parent capture becomes `unknown`.

`AuthenticatedSourceIngest` uses the vendored TMA-NM registry to classify a
signed envelope by registered transport identity; claims in the payload have no
say. A bad signature is downgraded to untrusted by the upstream registry. The
registry must be configured fail closed and owned by the harness. The current
adapter does not implement multi-domain endorsement or TMA-NM's full monitor.

Writes and quarantine updates use one connection with `ATTACH`, `BEGIN IMMEDIATE`
and a rollback journal. The main DB is a real file, neither DB uses WAL, and
both use `synchronous=EXTRA`. [SQLite documents cross-file atomic transactions
under these conditions](https://www.sqlite.org/lang_attach.html). Failed mirror
writes roll back the primary write. Reads compare every mirrored field and
recompute the content hash. Startup scans both ID sets and every captured
parent join under one database transaction, so concurrent writes cannot create
a false disagreement between separate SELECT statements. Missing or conflicting
copies fail closed; there is no automatic
copy reconstruction because it could hide tampering.

`seal_key` is an optional host-held secret of at least 32 bytes. When provided,
the mirror stores an HMAC-SHA256 over the canonical identity, version, hash,
label, status, parents and producer. Reopen requires the same key; matching
tampering of both files is rejected unless the attacker also has the key.
The key must live outside both DB files and model/tool access. Key rotation and
migration between sealed/unsealed databases are not implemented.

Two files under the same OS account are **not an independent security boundary**.
Without a separate key, an attacker with write access to both files can alter
both. Even with a key, a compromised host process can forge records. Hardening
options for deployment include an OS-separated service account and remote
append-only audit; neither is implemented.

`label_policy.py` checks exact task/operation/resource/recipient host grants,
evidence IDs and hashes, confidentiality and identity scope. `LabelSession`
binds canonical arguments, call ID, scope revision and evidence hashes into
the recovery `Proposal`; `SafeExecutor` consumes a fresh host grant exactly
once and records external effect status. Denials emit structured `LabelAlert`.
High-risk actions still require a host confirmation ID. External content can
be used as data when a separate host grant authorizes the action.

## Benchmark capture

- AgentLAB Email: `capture_agentlab_task` assigns the host user channel;
  `capture_agentlab_email` marks the tool result untrusted and identity scoped;
  `capture_summary` joins actual input IDs and adds model provenance.
- RedTeamCUA: `capture_redteam_task` assigns user channel;
  `capture_redteam_observation` records screenshot SHA-256 and accessibility
  text as external; `capture_summary` preserves that origin. The integrated
  runner stores a screenshot-hash source record and a model-derived perception
  record with a parent link. Full GUI benchmark execution remains unverified.
- `scripts/evaluate_labels.py` runs an offline contract experiment over the
  checked-in AgentLAB fixture and a synthetic RedTeam screen. This does not
  measure attack success rate, model behavior or GUI interception coverage.
- The current AgentLAB and RedTeamCUA main paths use `LabelSession`. Their
  benchmark adapters translate actual harness observations and proposed
  actions; the core label/recovery APIs contain no benchmark-specific types.
- `scripts/smoke_label_agentlab.py` runs normal, injection-repaired and
  unauthorized-send-blocked cases through the actual pinned AgentLAB Email
  environment using a scripted model. It reports fixture checks, not official
  benchmark scoring.

## Local verification and remaining integration

From PowerShell in the repository root:

```powershell
$env:ARIADNE_TMA_CHECKOUT = '<pinned mem-inv-bench checkout>'
$env:ARIADNE_SRR_CHECKOUT = '<pinned selective-revocation-replay checkout>'
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe scripts\smoke_label_agentlab.py --agentlab '<pinned AgentLAB checkout>'
```

The original 24 label tests cover propagation, versioning, dual-file failure,
tampering, channel classification and fixtures. New bridge/runtime tests cover
revision parity, interrupted normal-write projection, label-owned quarantine,
crash replay, repair publication,
action binding, structured alerts, unknown-state suspension and a synthetic
RedTeamCUA wrapper action. Full model/GUI benchmark evaluation remains with
the benchmark member. The team lead has selected the label ledger as authority;
the graph and recovery members must use this contract and test the graph
member's real adapter; the benchmark member must
run its official scorer and environment. The current smoke does not provide
those results.
