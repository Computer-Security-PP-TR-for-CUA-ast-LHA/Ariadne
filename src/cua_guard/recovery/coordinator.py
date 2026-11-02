"""Barrier-first, crash-resumable recovery of a complete scope."""
from .contracts import RecoveryError, Version
from .graph import VersionGraph


class RecoveryCoordinator:
    def __init__(self, store, backend, validator, projection, *, graph=None, max_nodes=10_000):
        self.store, self.backend, self.validator, self.projection = store, backend, validator, projection
        self.graph = graph or store
        if type(max_nodes) is not int or max_nodes < 1:
            raise ValueError('max_nodes must be positive')
        self.max_nodes = max_nodes
        for component in (backend, validator, projection):
            if not isinstance(component.identity, str) or not component.identity.strip():
                raise ValueError('Every adapter needs a stable configuration identity')

    def recover(self, request):
        with self.store.recovery_lock(request.scope_id):
            return self._recover_locked(request)

    def _recover_locked(self, request):
        # reserve failures (unknown scope, competing request, identity conflict) never
        # modify someone else's job. Recovery errors after reservation keep the barrier.
        job = self.store.reserve(request, {'backend': self.backend.identity,
            'validator': self.validator.identity, 'projection': self.projection.identity,
            'max_nodes': self.max_nodes, 'algorithm': 'barrier-all-or-nothing/1'})
        try:
            if job['state'] == 'ready':
                if not self.store.ready(request.scope_id, job['revision']):
                    return {**job, 'outcome': 'needs_review', 'error': 'historical_receipt'}
                return {**job, 'outcome': 'ready'}
            if job['state'] == 'reserved':
                snapshot = self.graph.snapshot(request.scope_id)
                graph = VersionGraph(snapshot, self.max_nodes)
                local = self.store.snapshot(request.scope_id)
                # External graph must describe this exact committed ledger revision.
                local_graph = VersionGraph(local, self.max_nodes)
                if (snapshot.scope_id != local.scope_id or snapshot.revision != local.revision
                    or graph.nodes != local_graph.nodes or graph.edges != local_graph.edges):
                    raise RecoveryError('graph_ledger_mismatch')
                bindings = self.store.call_bindings(request.scope_id, request.call_id) if request.call_id else None
                job = self.store.quarantine(request, graph.plan(request, bindings))
            if job['state'] == 'quarantined':
                nodes = VersionGraph(self.store.snapshot(request.scope_id), self.max_nodes).nodes
                if len(nodes) + sum(len(s['versions']) for s in job['staged'].values()) > self.max_nodes:
                    raise RecoveryError('graph_budget_exceeded')
                for vid in job['plan']['targets']:
                    if vid in job['staged']:
                        continue
                    old = nodes[vid]
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
                    validation = self.validator.validate(old, outputs, request.task)
                    if not validation.accepted():
                        raise RecoveryError('validation_rejected')
                    if len(nodes) + sum(len(s['versions']) for s in job['staged'].values()) + len(outputs) > self.max_nodes:
                        raise RecoveryError('graph_budget_exceeded')
                    if (sum(len(v.content) for v in nodes.values())
                        + sum(len(v['content']) for s in job['staged'].values() for v in s['versions'])
                        + sum(len(s) for s in outputs)) > 16_000_000:
                        raise RecoveryError('graph_content_budget_exceeded')
                    job = self.store.stage(request, old, outputs, tuple(inputs), validation)
                job = self.store.publish(request)
            if job['state'] == 'published':
                manifest = self.store.manifest(request.scope_id)
                if manifest['revision'] != job['revision']:
                    raise RecoveryError('revision_conflict')
                acknowledgment = self.projection.install(manifest)
                job = self.store.acknowledge(request, acknowledgment)
            return {**job, 'outcome': 'ready'}
        except Exception as exc:
            # Do not expose model responses, source contents, credentials or arbitrary
            # exception strings in public telemetry. BaseException preserves crash tests.
            code = exc.code if isinstance(exc, RecoveryError) else 'adapter_failed'
            job = self.store.fail(request, code)
            return {**job, 'outcome': 'needs_review'}
