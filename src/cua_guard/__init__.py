"""Host-side research primitives; not a production sandbox or injection detector."""

from .store import ProvenanceStore
from .gate import Action, Capability, Decision, ExecutionGate

__all__ = ["ProvenanceStore", "Action", "Capability", "Decision", "ExecutionGate"]
