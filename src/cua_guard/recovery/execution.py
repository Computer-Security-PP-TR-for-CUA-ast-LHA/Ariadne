"""Re-propose, independently authorize, then durably claim an external operation."""
from dataclasses import asdict, dataclass
import json
import math
from .contracts import RecoveryError, canonical, digest, identity


@dataclass(frozen=True)
class Proposal:
    scope_id: str
    session_id: str
    operation_id: str  # trusted host business-operation key, NOT model call_id
    revision: int
    bindings: tuple[tuple[str, str], ...]
    tool: str
    arguments_json: str

    def __post_init__(self):
        for x in (self.scope_id, self.session_id, self.operation_id, self.tool):
            identity(x)
        if type(self.revision) is not int or self.revision < 0:
            raise RecoveryError('invalid_revision')
        if not isinstance(self.bindings, tuple) or any(not isinstance(b, tuple) or len(b) != 2 for b in self.bindings):
            raise RecoveryError('invalid_action_binding')
        if not isinstance(self.arguments_json, str) or len(self.arguments_json) > 100_000:
            raise RecoveryError('invalid_arguments')
        try:
            args = json.loads(self.arguments_json)
            if not isinstance(args, dict) or canonical(args) != self.arguments_json:
                raise RecoveryError('noncanonical_arguments')
        except (ValueError, TypeError) as exc:
            raise RecoveryError('invalid_arguments') from exc

    @property
    def fingerprint(self):
        return digest(canonical(asdict(self)))


@dataclass(frozen=True)
class AuthorizationGrant:
    """Created only by a trusted independent host authorizer, never from model JSON."""
    grant_id: str
    proposal_hash: str
    epoch: int
    expires_at: float

    def __post_init__(self):
        identity(self.grant_id)
        if (not isinstance(self.proposal_hash, str) or len(self.proposal_hash) != 64
            or type(self.epoch) is not int or self.epoch < 0
            or type(self.expires_at) not in (int, float) or not math.isfinite(self.expires_at)):
            raise RecoveryError('invalid_grant')


class SafeExecutor:
    def __init__(self, store, authorizer, execute):
        """authorizer(proposal) returns AuthorizationGrant only on independent grant.

        Host authorizer must bind task, recipient, resource, fields, operation and
        policy epoch as appropriate. Authorization is not inferred from repair.
        execute receives detached (tool, arguments, idempotency_key).
        """
        self.store, self.authorizer, self.execute = store, authorizer, execute

    def dispatch(self, proposal: Proposal):
        grant = self.authorizer(proposal)
        if not isinstance(grant, AuthorizationGrant) or grant.proposal_hash != proposal.fingerprint:
            raise RecoveryError('authorization_denied')
        self.store.claim_effect(proposal.scope_id, proposal.session_id, proposal.operation_id,
                                proposal.revision, proposal.bindings, asdict(proposal), grant)
        try:
            result = self.execute(proposal.tool, json.loads(proposal.arguments_json), proposal.operation_id)
            canonical(result)  # non-serializable outcome is ambiguous, never replay
            self.store.finish_effect(proposal.scope_id, proposal.operation_id, result)
        except Exception as exc:
            self.store.finish_effect(proposal.scope_id, proposal.operation_id, unknown=True)
            raise RecoveryError('effect_outcome_unknown') from exc
        return result
