"""Wire contracts. Inputs are supplied by trusted host adapters, never by prose."""
from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Protocol

SCHEMA = 'ariadne.recovery/0.2'


class RecoveryError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def identity(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise RecoveryError('invalid_identity')


@dataclass(frozen=True)
class Version:
    version_id: str
    artifact_id: str
    content: str
    content_sha256: str
    origins: tuple[str, ...]
    parents: tuple[str, ...] = ()
    status: str = 'active'
    writer_key: str | None = None
    session_id: str = ''

    def __post_init__(self):
        identity(self.version_id)
        identity(self.artifact_id)
        if not isinstance(self.content, str) or len(self.content) > 100_000:
            raise RecoveryError('invalid_content')
        if digest(self.content) != self.content_sha256:
            raise RecoveryError('hash_mismatch')
        if not isinstance(self.origins, tuple) or not self.origins or any(not isinstance(x, str) or not x for x in self.origins):
            raise RecoveryError('missing_origin')
        if not isinstance(self.parents, tuple) or len(set(self.parents)) != len(self.parents):
            raise RecoveryError('invalid_parents')
        for parent in self.parents:
            identity(parent)
        if self.status not in {'active', 'quarantined', 'staged', 'superseded'}:
            raise RecoveryError('invalid_status')
        if self.writer_key is not None:
            identity(self.writer_key)
        if not isinstance(self.session_id, str) or len(self.session_id) > 512:
            raise RecoveryError('invalid_session')

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or not isinstance(value.get('origins'), (list, tuple)) or not isinstance(value.get('parents', ()), (list, tuple)):
            raise RecoveryError('invalid_version_payload')
        return cls(**{**value, 'origins': tuple(value['origins']), 'parents': tuple(value.get('parents', ()))})


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    kind: str = 'derived_from'


@dataclass(frozen=True)
class Snapshot:
    scope_id: str
    revision: int
    versions: tuple[Version, ...]
    edges: tuple[Edge, ...]
    coverage: str = 'complete_within_scope'
    missing_refs: tuple[str, ...] = ()
    schema_version: str = SCHEMA

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or any(not isinstance(value.get(k), (list, tuple)) for k in ('versions', 'edges')):
            raise RecoveryError('invalid_graph_payload')
        allowed = {'scope_id','revision','versions','edges','coverage','missing_refs','schema_version'}
        if set(value) - allowed:
            raise RecoveryError('unsupported_graph_fields')
        if not isinstance(value.get('missing_refs', ()), (list, tuple)):
            raise RecoveryError('invalid_graph_payload')
        if value.get('schema_version') != SCHEMA:
            raise RecoveryError('unsupported_schema')
        return cls(value['scope_id'], value['revision'],
                   tuple(Version.from_dict(v) for v in value['versions']),
                   tuple(Edge(**e) for e in value['edges']), value['coverage'],
                   tuple(value.get('missing_refs', ())), value['schema_version'])


@dataclass(frozen=True)
class RecoveryRequest:
    request_id: str
    scope_id: str
    task: str
    roots: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reason: str = 'pollution_confirmed'
    call_id: str | None = None

    def __post_init__(self):
        identity(self.request_id)
        identity(self.scope_id)
        if not isinstance(self.task, str) or not self.task.strip() or len(self.task) > 100_000:
            raise RecoveryError('invalid_task')
        if not isinstance(self.roots, tuple) or not isinstance(self.evidence_refs, tuple):
            raise RecoveryError('invalid_request')
        for value in (*self.roots, *self.evidence_refs):
            identity(value)
        if len(set(self.roots)) != len(self.roots):
            raise RecoveryError('duplicate_root')
        if self.reason not in {'pollution_confirmed', 'suspected_pollution', 'missing_authority', 'integrity_mismatch', 'unknown'}:
            raise RecoveryError('invalid_reason')
        if self.call_id is not None:
            identity(self.call_id)


@dataclass(frozen=True)
class Validation:
    safe: bool
    faithful: bool
    evidence: str

    def accepted(self):
        return self.safe is True and self.faithful is True and isinstance(self.evidence, str) and bool(self.evidence.strip())


class GraphPort(Protocol):
    def snapshot(self, scope_id: str) -> Snapshot: ...


class RepairBackend(Protocol):
    # Identity must include model, prompts/config, upstream version and replay registry.
    identity: str

    def repair(self, old: Version, inputs: tuple[Version, ...], task: str) -> tuple[str, ...]: ...


class Validator(Protocol):
    identity: str

    def validate(self, old: Version, outputs: tuple[str, ...], task: str) -> Validation: ...


class ProjectionPort(Protocol):
    # Idempotent: install exactly this manifest and reset the managed context.
    # Return its digest only after retrieval + context are both installed.
    identity: str

    def install(self, manifest: dict) -> str: ...


class RecoveryStorePort(Protocol):
    """Storage unit-of-work; each mutator is atomic and checks ownership/revision.

    Implementations must enforce the same visibility and effect barriers as SQLite.
    JSON-shaped return values are specified in docs/recovery/implementation.md.
    """
    def recovery_lock(self, scope: str): ...
    def workflow_path(self, scope: str) -> str: ...
    def reserve(self, request: RecoveryRequest, configuration: dict) -> dict: ...
    def job(self, scope: str, request_id: str) -> dict: ...
    def snapshot(self, scope_id: str) -> Snapshot: ...
    def call_bindings(self, scope: str, call_id: str) -> tuple[str, ...]: ...
    def quarantine(self, request: RecoveryRequest, plan: dict) -> dict: ...
    def stage(self, request: RecoveryRequest, old: Version, outputs: tuple[str, ...],
              inputs: tuple[Version, ...], validation: Validation) -> dict: ...
    def publish(self, request: RecoveryRequest) -> dict: ...
    def manifest(self, scope: str) -> dict: ...
    def acknowledge(self, request: RecoveryRequest, manifest_digest: str) -> dict: ...
    def fail(self, request: RecoveryRequest, code: str) -> dict: ...
    def ready(self, scope: str, revision: int) -> bool: ...
