"""Host-issued action scope over persistent labels.

Memory text never creates a capability. A label is an input constraint, not
proof that the user authorized an action. The host must bind exact arguments,
recipient and bytes at dispatch time to prevent time-of-check/time-of-use drift.
"""
from __future__ import annotations

from dataclasses import dataclass

from .label_store import Confidentiality, Integrity, LabelConflict, PersistentLabelStore


@dataclass(frozen=True)
class Evidence:
    node_id: str
    observed_hash: str


@dataclass(frozen=True)
class Action:
    task_id: str
    operation: str
    resource: str
    recipient: str
    evidence: tuple[Evidence, ...]
    risk: str = "low"


@dataclass(frozen=True)
class HostGrant:
    """Construct only from an authenticated task/policy event outside the model."""
    task_id: str
    operation: str
    resource: str
    recipient: str
    max_confidentiality: Confidentiality = Confidentiality.PUBLIC
    allowed_principals: frozenset[str] = frozenset()
    confirmation_id: str | None = None
    require_trusted_evidence: bool = False


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str


def check_action(store: PersistentLabelStore, action: Action,
                 grant: HostGrant | None) -> Decision:
    """Deterministic pre-dispatch check; never execute a tool here."""
    if not all((action.task_id, action.operation, action.resource)):
        return Decision(False, "missing_action_identity")
    if action.risk not in {"low", "high"}:
        return Decision(False, "unsupported_risk")
    if grant is None or (action.task_id, action.operation, action.resource, action.recipient) != (
            grant.task_id, grant.operation, grant.resource, grant.recipient):
        return Decision(False, "outside_host_grant")
    # Email delivery always carries an external side effect, including callers
    # that rely on Action's default risk classification.
    high_risk = action.risk == "high" or action.operation == "send_email"
    if high_risk and not grant.confirmation_id:
        return Decision(False, "missing_direct_confirmation")
    if not action.evidence:
        return Decision(False, "missing_evidence")
    rank = {Confidentiality.PUBLIC: 0, Confidentiality.PRIVATE: 1,
            Confidentiality.USER_IDENTITY: 2}
    try:
        for item in action.evidence:
            record = store.read(item.node_id)
            if record.status != "active":
                return Decision(False, "inactive_evidence")
            if record.content_hash != item.observed_hash:
                return Decision(False, "changed_evidence")
            if "unknown" in record.label.origins:
                return Decision(False, "unknown_origin")
            if (high_risk or grant.require_trusted_evidence) and record.label.integrity != Integrity.TRUSTED:
                return Decision(False, "untrusted_evidence")
            if rank[record.label.confidentiality] > rank[grant.max_confidentiality]:
                return Decision(False, "confidentiality_exceeds_grant")
            if record.label.principals and not record.label.principals <= grant.allowed_principals:
                return Decision(False, "principal_mismatch")
    except KeyError:
        return Decision(False, "unknown_evidence")
    except (LabelConflict, ValueError):
        return Decision(False, "label_conflict")
    return Decision(True, "host_grant_and_labels_valid")
