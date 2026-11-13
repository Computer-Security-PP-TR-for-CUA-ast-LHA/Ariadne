"""Trusted host events projected into the graph and recovery contracts.

Label UUIDs remain authoritative. The graph's ``m_`` IDs are a reversible
representation of those UUIDs, never a second version namespace.
"""
from __future__ import annotations

from dataclasses import dataclass

from .provenance import ProvenanceRecorder, validate_graph
from .recovery.contracts import RecoveryError


def memory_id(version_id: str) -> str:
    return "m_" + version_id


@dataclass(frozen=True)
class HostStep:
    step_id: str
    step_type: str
    used_ids: tuple[str, ...] = ()
    generated_memory_ids: tuple[str, ...] = ()
    metadata: dict | None = None


class LabelProvenancePort:
    """Record host calls and require graph/ledger parity before recovery.

    The host must call the on_* hooks at the actual read, write and action
    sites. The port does not infer an omitted read from text or chronology.
    """

    def __init__(self, bridge, task: str):
        self.bridge = bridge
        self.task = task
        self.steps: list[HostStep] = []
        self._written: set[str] = set()
        self._last_action: str | None = None
        self.snapshot_calls = 0

    def _step(self, step_type: str, *, used=(), produced=(), **metadata) -> str:
        step_id = f"s_{len(self.steps) + 1:06d}"
        self.steps.append(HostStep(step_id, step_type, tuple(used),
                                   tuple(produced), metadata))
        return step_id

    def on_session_start(self, version_id: str) -> None:
        self.on_capture(version_id, "task", ())

    def on_capture(self, version_id: str, artifact: str,
                   parents: tuple[str, ...]) -> None:
        if version_id in self._written:
            raise RecoveryError("duplicate_host_write")
        self._written.add(version_id)
        used = tuple(memory_id(parent) for parent in parents)
        if artifact.startswith("tool-result:") and self._last_action:
            used += (self._last_action,)
        self._step("memory_write", used=used,
                   produced=(memory_id(version_id),), artifact=artifact,
                   version_id=version_id)

    def on_read(self, version_ids: tuple[str, ...], *, purpose: str,
                call_id: str | None = None) -> None:
        first_read = not any(step.step_type == "memory_read" for step in self.steps)
        self._step("memory_read" if first_read else "plan",
                   used=tuple(memory_id(v) for v in version_ids),
                   purpose=purpose, call_id=call_id,
                   ledger_revision=self.bridge.labels.revision())

    def on_action(self, call_id: str, tool: str, version_ids: tuple[str, ...],
                  *, allowed: bool, payload_hash: str) -> None:
        self._last_action = self._step(
            "tool_action", used=tuple(memory_id(v) for v in version_ids),
            call_id=call_id, tool=tool, allowed=allowed,
            payload_hash=payload_hash,
            ledger_revision=self.bridge.labels.revision())

    def on_tool_observation(self, tool: str) -> None:
        if self._last_action is None:
            raise RecoveryError("missing_tool_action")
        self._last_action = self._step(
            "tool_observation", used=(self._last_action,), tool=tool)

    def _sync_recovery_writes(self) -> None:
        # Recovery publishes versions through its own coordinator, not through
        # LabelSession.capture. Its committed ledger events are host evidence.
        for record in self.bridge.labels.records():
            if record.id not in self._written:
                self.on_capture(record.id, record.artifact, record.parents)

    def on_recovery_commit(self) -> None:
        self._sync_recovery_writes()
        self.snapshot(self.bridge.scope_id)

    def build(self):
        self.bridge.labels.scan_consistency()
        current_ids = {record.id for record in self.bridge.labels.records()}
        if self._written != current_ids:
            raise RecoveryError("missing_host_write")
        recorder = ProvenanceRecorder(self.bridge.scope_id)
        recorder.record_user_input(self.task)
        steps = tuple(self.steps)
        for index, step in enumerate(steps):
            recorder.record_step(
                step.step_id, step.step_type,
                next_step_ids=(steps[index + 1].step_id,) if index + 1 < len(steps) else (),
                used_ids=step.used_ids,
                generated_memory_ids=step.generated_memory_ids,
                **(step.metadata or {}))
        for record in self.bridge.labels.records():
            recorder.record_memory(
                memory_id(record.id), status=record.status,
                derived_from=tuple(memory_id(v) for v in record.parents),
                version_id=record.id,
                content_sha256=record.content_hash,
                created_revision=record.created_revision)
        graph = recorder.build()
        validate_graph(graph).raise_for_errors()
        return graph

    def snapshot(self, scope_id: str):
        if scope_id != self.bridge.scope_id:
            raise RecoveryError("scope_mismatch")
        self.snapshot_calls += 1
        graph = self.build()
        snapshot = self.bridge.label_snapshot()
        version_ids = {v.version_id for v in snapshot.versions}
        graph_ids = {node.raw["version_id"] for node in graph.nodes.values()
                     if node.node_kind.value == "memory"}
        if graph_ids != version_ids:
            raise RecoveryError("provenance_version_mismatch")
        graph_parents = {
            (source[2:], target[2:])
            for source, destinations in graph.forward_edges.items()
            for target, labels in destinations.items()
            if "derive" in labels
        }
        ledger_parents = {(edge.source, edge.target) for edge in snapshot.edges
                          if edge.kind == "derived_from"}
        if graph_parents != ledger_parents:
            raise RecoveryError("provenance_parent_mismatch")
        return snapshot
