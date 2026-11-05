"""Typed reachability + stdlib topological order. No claim of semantic causality."""
from graphlib import CycleError, TopologicalSorter
from .contracts import Edge, RecoveryError, Snapshot, SCHEMA, identity
from .dgrr import DGRRReachability

DATA = frozenset({'derived_from'})
AUDIT = frozenset({'sanitized_from', 'supersedes'})
KINDS = DATA | AUDIT | {'sequence', 'supports'}


class VersionGraph:
    def __init__(self, snapshot: Snapshot, max_nodes=10_000, *, reachability=None):
        self.snapshot = snapshot
        self.reachability = reachability or DGRRReachability()
        identity(snapshot.scope_id)
        if snapshot.schema_version != SCHEMA:
            raise RecoveryError('unsupported_schema')
        if type(snapshot.revision) is not int or snapshot.revision < 0:
            raise RecoveryError('invalid_revision')
        if snapshot.coverage != 'complete_within_scope' or snapshot.missing_refs:
            raise RecoveryError('incomplete_graph')
        if len(snapshot.versions) > max_nodes or len(snapshot.edges) > max_nodes * 32:
            raise RecoveryError('graph_budget_exceeded')
        if sum(len(v.content) for v in snapshot.versions) > 16_000_000:
            raise RecoveryError('graph_content_budget_exceeded')
        self.nodes = {v.version_id: v for v in snapshot.versions}
        if len(self.nodes) != len(snapshot.versions):
            raise RecoveryError('duplicate_version')
        self.edges = set(snapshot.edges)
        for e in self.edges:
            if e.source not in self.nodes or e.target not in self.nodes:
                raise RecoveryError('missing_edge_endpoint')
            if e.kind not in KINDS:
                raise RecoveryError('unsupported_edge')
        for v in snapshot.versions:
            for parent in v.parents:
                if Edge(parent, v.version_id) not in self.edges:
                    raise RecoveryError('missing_parent_edge')
                if not set(self.nodes[parent].origins) <= set(v.origins):
                    raise RecoveryError('origin_downgrade')
        for e in self.edges:
            if e.kind in DATA and e.source not in self.nodes[e.target].parents:
                raise RecoveryError('parent_edge_mismatch')
        self.order = self.topological(self.nodes, DATA | AUDIT)

    def closure(self, roots, kinds=DATA, reverse=False):
        roots = set(roots)
        if not roots or not roots <= self.nodes.keys():
            raise RecoveryError('unknown_root')
        selected = {edge for edge in self.edges if edge.kind in kinds}
        return self.reachability.closure(
            self.nodes, selected, tuple(sorted(roots)), reverse=reverse
        )

    def topological(self, ids, kinds=DATA):
        ids = set(ids)
        deps = {n: set() for n in sorted(ids)}
        for e in self.edges:
            if e.kind in kinds and e.source in ids and e.target in ids:
                deps[e.target].add(e.source)
        try:
            return tuple(TopologicalSorter({n: sorted(v) for n, v in deps.items()}).static_order())
        except CycleError as exc:
            raise RecoveryError('cycle_detected') from exc

    def plan(self, request, call_bindings=None):
        if request.scope_id != self.snapshot.scope_id:
            raise RecoveryError('scope_mismatch')
        if request.reason != 'pollution_confirmed' or not request.evidence_refs:
            raise RecoveryError('diagnosis_required')
        if call_bindings is not None:
            ancestry = self.closure(call_bindings, DATA | AUDIT, reverse=True)
            if not set(request.roots) <= ancestry:
                raise RecoveryError('root_outside_call_ancestry')
        # Audit descendants are revalidated conservatively for late alerts.
        affected = self.closure(request.roots, DATA | AUDIT)
        targets = {n for n in affected if self.nodes[n].status in {'active', 'quarantined'}}
        if not targets:
            raise RecoveryError('no_repairable_versions')
        if any(self.nodes[n].status == 'staged' for n in affected):
            raise RecoveryError('unexpected_staged_version')
        return {'scope_id': request.scope_id, 'revision': self.snapshot.revision,
                'roots': list(request.roots), 'affected': sorted(affected),
                'targets': list(self.topological(targets)),
                'preserved': sorted(n for n, v in self.nodes.items() if v.status == 'active' and n not in targets)}
