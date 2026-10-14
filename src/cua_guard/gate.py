"""Exact action-scope checking for a trusted dispatch adapter.

No wildcard URL/path semantics. Resource names are harness-issued identifiers.
No native clicks, shell, network, or process isolation are implemented here.
"""
from dataclasses import asdict, dataclass
from typing import Callable, TypeVar

from .store import ProvenanceStore

T = TypeVar("T")


@dataclass(frozen=True)
class Action:
    call_id: str
    task_id: str
    operation: str
    resource: str
    recipient: str
    bindings: tuple[tuple[str, str], ...]  # node ID, observed content digest


@dataclass(frozen=True)
class Capability:
    """Constructed by trusted host policy, never model-produced JSON."""
    task_id: str
    operation: str
    resource: str
    recipient: str


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


class ExecutionGate:
    def __init__(self, store: ProvenanceStore):
        self.store = store

    def check(self, action: Action, capabilities: tuple[Capability, ...]) -> Decision:
        required = Capability(action.task_id, action.operation, action.resource, action.recipient)
        if not all((action.call_id, action.task_id, action.operation, action.resource)):
            return Decision(False, "missing_action_identity")
        if required not in capabilities:
            return Decision(False, "outside_task_capability")
        if not action.bindings:
            return Decision(False, "missing_provenance")
        for node_id, observed_hash in action.bindings:
            try:
                n = self.store.get(node_id)
            except KeyError:
                return Decision(False, "unknown_version")
            if n["status"] != "active":
                return Decision(False, "quarantined_version")
            if n["hash"] != observed_hash:
                return Decision(False, "content_changed")
            if "unknown" in n["origins"]:
                return Decision(False, "unknown_origin")
        # External information is usable as data, under independent exact scope.
        # Capabilities are not derived from provenance or document instructions.
        return Decision(True, "within_host_scope")

    def dispatch(self, action: Action, capabilities: tuple[Capability, ...],
                 executor: Callable[[Action], T]) -> T:
        decision = self.check(action, capabilities)
        # Duplicate call IDs fail before dispatch, including across restarts.
        self.store.record_call(action.call_id, asdict(action), decision.reason)
        if not decision.allowed:
            raise PermissionError(decision.reason)
        # Executor receives precisely the immutable checked action. In a real
        # adapter it must bind current bytes/recipient and prevent TOCTOU itself.
        return executor(action)
