"""Domain recovery policy on the upstream LangGraph durable execution engine."""
from .contracts import RecoveryError, Version, digest
from .dgrr import DGRRReachability
from .graph import VersionGraph
from .workflow import invoke_recovery


class RecoveryCoordinator:
    def __init__(self, store, backend, validator, projection, *, graph=None,
                 reachability=None, max_nodes=10_000):
        self.store, self.backend, self.validator, self.projection = store, backend, validator, projection
        self.graph = graph or store
        self.reachability = reachability or DGRRReachability()
        if type(max_nodes) is not int or max_nodes < 1:
            raise ValueError('max_nodes must be positive')
        self.max_nodes = max_nodes
        for component in (backend, validator, projection):
            if not isinstance(component.identity, str) or not component.identity.strip():
                raise ValueError('Every adapter needs a stable configuration identity')
        if (not isinstance(self.reachability.identity, str)
                or not self.reachability.identity.strip()):
            raise ValueError('Graph backend needs a stable configuration identity')

    def recover(self, request):
        with self.store.recovery_lock(request.scope_id):
            job = self.store.reserve(request, {'backend': self.backend.identity,
                'validator': self.validator.identity, 'projection': self.projection.identity,
                'graph_backend': self.reachability.identity,
                'max_nodes': self.max_nodes, 'algorithm': 'langgraph-barrier/1'})
            if job['state'] == 'ready':
                current = self.store.ready(request.scope_id, job['revision'])
                if not current:
                    return {**job,'outcome':'needs_review','error':'historical_receipt'}
            return invoke_recovery(self, request)

    def prepare(self, request):
        # Idempotent across the domain SQL commit / workflow checkpoint gap.
        job = self.store.job(request.scope_id, request.request_id)
        if job['state'] != 'reserved':
            return job
        snapshot = self.graph.snapshot(request.scope_id)
        graph = VersionGraph(snapshot, self.max_nodes, reachability=self.reachability)
        local = self.store.snapshot(request.scope_id)
        local_graph = VersionGraph(local, self.max_nodes)
        if (snapshot.scope_id != local.scope_id or snapshot.revision != local.revision
            or graph.nodes != local_graph.nodes or graph.edges != local_graph.edges):
            raise RecoveryError('graph_ledger_mismatch')
        bindings = self.store.call_bindings(request.scope_id, request.call_id) if request.call_id else None
        return self.store.quarantine(request, graph.plan(request, bindings))

    def repair_one(self, request):
        job = self.store.job(request.scope_id, request.request_id)
        remaining = [vid for vid in job['plan']['targets'] if vid not in job['staged']]
        if not remaining:
            return job
        nodes = VersionGraph(self.store.snapshot(request.scope_id), self.max_nodes).nodes
        old = nodes[remaining[0]]
        inputs = []
        for parent in old.parents:
            if parent in job['plan']['targets']:
                if parent not in job['staged']:
                    raise RecoveryError('predecessor_not_ready')
                inputs.extend(Version.from_dict(v) for v in job['staged'][parent]['versions'])
            else:
                if nodes[parent].status != 'active':
                    raise RecoveryError('inactive_dependency')
                inputs.append(nodes[parent])
        outputs = self.backend.repair(old, tuple(inputs), request.task)
        if not isinstance(outputs, tuple) or not 1 <= len(outputs) <= 16 or any(
            not isinstance(s, str) or not s.strip() or len(s) > 100_000 for s in outputs):
            raise RecoveryError('invalid_replacement')
        contextual = getattr(self.validator, 'validate_with_inputs', None)
        validation = (contextual(old, tuple(inputs), outputs, request.task) if contextual
                      else self.validator.validate(old, outputs, request.task))
        if not validation.accepted():
            raise RecoveryError('validation_rejected', review={
                'target': old.version_id, 'artifact': old.artifact_id,
                'input_ids': [v.version_id for v in inputs],
                'candidates': [{'sha256': digest(s), 'preview': s[:512]} for s in outputs],
                'safe': validation.safe, 'faithful': validation.faithful,
                'evidence': validation.evidence,
            })
        if len(nodes) + sum(len(s['versions']) for s in job['staged'].values()) + len(outputs) > self.max_nodes:
            raise RecoveryError('graph_budget_exceeded')
        if (sum(len(v.content) for v in nodes.values())
            + sum(len(v['content']) for s in job['staged'].values() for v in s['versions'])
            + sum(len(s) for s in outputs)) > 16_000_000:
            raise RecoveryError('graph_content_budget_exceeded')
        return self.store.stage(request, old, outputs, tuple(inputs), validation)
