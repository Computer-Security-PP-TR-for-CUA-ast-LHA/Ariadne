"""Offline contract and failure-injection tests; no claims about LLM accuracy."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
import uuid
import unittest

from cua_guard.recovery import RecoveryCoordinator, SQLiteRecoveryStore
from cua_guard.recovery.contracts import Edge, RecoveryError, RecoveryRequest, Snapshot, Validation, Version, canonical, digest
from cua_guard.recovery.dgrr import DGRRReachability, DependencyGraph, affected_node_ids
from cua_guard.recovery.graph import VersionGraph
from cua_guard.recovery.adapters import CapturedWriterEvent, DualLabelProjection, JSONGraphAdapter, ManagedContextProjection, snapshot_from_events
from cua_guard.recovery.execution import AuthorizationGrant, Proposal, SafeExecutor
from cua_guard.recovery.semantic import ModelRepairBackend, ModelRepairValidator


def version(vid, text, parents=(), writer=None):
    return Version(vid, 'artifact/' + vid, text, digest(text), ('external',), parents, writer_key=writer)


def fixture():
    vs = (version('root', 'fact; INJECT'), version('summary', 'fact; INJECT', ('root',), 'copy'),
          version('dormant', 'fact; INJECT', ('summary',), 'copy'), version('good', 'unrelated'))
    return Snapshot('tenant', 0, vs, (Edge('root', 'summary'), Edge('summary', 'dormant'), Edge('root', 'good', 'sequence')))


class DGRRGraphTests(unittest.TestCase):
    def setUp(self):
        self.nodes = {'root-a', 'root-b', 'summary', 'copy', 'independent'}
        self.edges = {
            Edge('root-a', 'summary'),
            Edge('root-b', 'summary', 'supports'),
            Edge('summary', 'copy'),
        }

    def test_multi_seed_affected_nodes_are_deduplicated(self):
        graph = DependencyGraph(self.nodes, self.edges)
        self.assertEqual(
            affected_node_ids(graph, 'root-a', 'root-b'),
            ('summary', 'copy'),
        )
        self.assertEqual(graph.edge_kinds('root-b', 'summary'), {'supports'})

    def test_reverse_projection_finds_ancestors(self):
        self.assertEqual(
            DGRRReachability().closure(
                self.nodes, self.edges, ('copy',), reverse=True
            ),
            {'root-a', 'root-b', 'summary', 'copy'},
        )

    def test_unknown_root_fails_closed(self):
        with self.assertRaisesRegex(RecoveryError, 'unknown_root'):
            DGRRReachability().closure(
                self.nodes, self.edges, ('missing',)
            )


class FixtureBackend:
    identity = 'fixture-cleaner/1'
    def __init__(self):
        self.calls = []
    def repair(self, old, inputs, task):
        self.calls.append(old.version_id)
        return (old.content.replace('; INJECT', ''),)


class WriterRegistryBackend:
    """Test double retained from the pre-upstream implementation, not shipped."""
    def __init__(self, sanitizer, writers, *, registry_version):
        self.sanitizer, self.writers = sanitizer, dict(writers)
        self.identity = 'fixture-writers/' + registry_version + '/' + sanitizer.identity

    def repair(self, old, inputs, task):
        if old.writer_key is None:
            return self.sanitizer.repair(old, inputs, task)
        writer = self.writers.get(old.writer_key)
        if writer is None:
            raise RecoveryError('unknown_writer')
        if not inputs:
            raise RecoveryError('writer_without_support')
        return writer(inputs, task)


class FixtureValidator:
    identity = 'fixture-validator/1'
    def validate(self, old, outputs, task):
        return Validation(all('INJECT' not in x for x in outputs), 'fact' in ' '.join(outputs), 'fixture-expectation')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'state.db'
        self.store = SQLiteRecoveryStore(self.path)
        self.store.seed(fixture(), {'current': ('summary', 'good'), 'later': ('dormant',)})
        self.store.record_call('tenant', 'call', ('summary',))
        self.cleaner = FixtureBackend()
        self.backend = WriterRegistryBackend(self.cleaner, {'copy': lambda inputs, task: tuple(v.content for v in inputs)}, registry_version='1')
        self.validator = FixtureValidator()
        self.projection = ManagedContextProjection(self.store)
        self.request = RecoveryRequest('repair', 'tenant', 'Use fact', ('root',), ('host-evidence/1',), call_id='call')

    def coordinator(self, **changes):
        return RecoveryCoordinator(changes.pop('store', self.store), changes.pop('backend', self.backend),
            changes.pop('validator', self.validator), changes.pop('projection', self.projection), **changes)

    def proposal(self, op='business-operation', revision=None):
        rev, nodes = self.store.context('tenant', 'current')
        return Proposal('tenant', 'current', op, rev if revision is None else revision,
                        tuple((v.version_id, v.content_sha256) for v in nodes), 'send', canonical({'recipient': 'approved'}))

    def authorize(self, proposal):
        return AuthorizationGrant(str(uuid.uuid4()), proposal.fingerprint,
                                  self.store.authority_epoch(proposal.scope_id), time.time() + 60)

    def test_end_to_end_preserves_clean_and_rebuilds_dormant(self):
        result = self.coordinator().recover(self.request)
        self.assertEqual(result['outcome'], 'ready')
        self.assertEqual(set(result['mapping']), {'root', 'summary', 'dormant'})
        self.assertEqual(result['plan']['preserved'], ['good'])
        rev, current = self.store.context('tenant', 'current')
        _, later = self.store.context('tenant', 'later')
        self.assertEqual([v.content for v in current], ['fact', 'unrelated'])
        self.assertEqual([v.content for v in later], ['fact'])
        self.assertEqual(current[1], fixture().versions[-1])
        self.assertTrue(all(v.origins == ('external',) for v in current))
        self.assertEqual(self.cleaner.calls, ['root'])
        nodes = VersionGraph(self.store.snapshot('tenant')).nodes
        for old in result['mapping']:
            self.assertEqual(nodes[old].status, 'superseded')
        _, messages = self.projection.messages('tenant', 'current', 'Use fact')
        self.assertNotIn('INJECT', canonical(messages))
        self.assertEqual(rev, 2)

    def test_idempotent_reopen(self):
        a = self.coordinator().recover(self.request)
        reopened = SQLiteRecoveryStore(self.path)
        b = self.coordinator(store=reopened, projection=ManagedContextProjection(reopened)).recover(self.request)
        self.assertEqual(a['mapping'], b['mapping'])
        self.assertEqual(self.cleaner.calls, ['root'])

    def test_request_id_reuse_rejected(self):
        self.coordinator().recover(self.request)
        with self.assertRaisesRegex(RecoveryError, 'request_id_conflict'):
            self.coordinator().recover(replace(self.request, task='Different task'))

    def test_unknown_root_blocks_without_mutating_content(self):
        result = self.coordinator().recover(replace(self.request, roots=('missing',), call_id=None))
        self.assertEqual(result['error'], 'unknown_root')
        self.assertEqual(self.store.snapshot('tenant').versions, tuple(sorted(fixture().versions, key=lambda v:v.version_id)))
        with self.assertRaisesRegex(RecoveryError, 'scope_blocked'):
            self.store.context('tenant', 'current')

    def test_permission_denial_is_not_pollution(self):
        result = self.coordinator().recover(replace(self.request, reason='missing_authority'))
        self.assertEqual(result['error'], 'diagnosis_required')
        self.assertIsNone(result['plan'])

    def test_root_must_belong_to_call(self):
        result = self.coordinator().recover(replace(self.request, roots=('good',)))
        self.assertEqual(result['error'], 'root_outside_call_ancestry')

    def test_missing_evidence_rejected(self):
        result = self.coordinator().recover(replace(self.request, evidence_refs=()))
        self.assertEqual(result['error'], 'diagnosis_required')

    def test_competing_recovery_rejected(self):
        self.store.reserve(self.request, {})
        with self.assertRaisesRegex(RecoveryError, 'scope_busy'):
            self.coordinator().recover(replace(self.request, request_id='another'))

    def test_same_scope_worker_lock(self):
        other = SQLiteRecoveryStore(self.path)
        with self.store.recovery_lock('tenant'):
            with self.assertRaisesRegex(RecoveryError, 'scope_worker_busy'):
                with other.recovery_lock('tenant'):
                    self.fail('concurrent worker acquired lock')

    def test_barrier_precedes_backend_and_blocks_writes(self):
        cleaner = self.cleaner
        original = cleaner.repair
        def checked(old, inputs, task):
            with self.assertRaisesRegex(RecoveryError, 'scope_blocked'):
                self.store.context('tenant', 'current')
            with self.assertRaisesRegex(RecoveryError, 'scope_blocked'):
                self.store.append('tenant', version('new', 'x'), 'current')
            self.assertEqual({v.status for v in self.store.snapshot('tenant').versions if v.version_id != 'good'}, {'quarantined'})
            return original(old, inputs, task)
        cleaner.repair = checked
        self.assertEqual(self.coordinator().recover(self.request)['outcome'], 'ready')

    def test_invalid_validator_does_not_publish(self):
        self.validator.validate = lambda *args: Validation(True, False, 'fact lost')
        result = self.coordinator().recover(self.request)
        self.assertEqual(result['error'], 'validation_rejected')
        self.assertEqual(len(self.store.snapshot('tenant').versions), 4)

    def test_empty_outputs_not_success(self):
        self.cleaner.repair = lambda *args: ()
        self.assertEqual(self.coordinator().recover(self.request)['error'], 'invalid_replacement')

    def test_unknown_writer_fails_closed(self):
        self.backend.writers.clear()
        result = self.coordinator().recover(self.request)
        self.assertEqual(result['error'], 'unknown_writer')
        self.assertIn('root', result['staged'])
        self.assertEqual(len(self.store.snapshot('tenant').versions), 4)

    def test_split_replacements_preserve_all_parent_versions(self):
        self.cleaner.repair = lambda *args: ('fact A', 'fact B')
        result = self.coordinator().recover(self.request)
        self.assertEqual(result['outcome'], 'ready')
        self.assertEqual(len(result['mapping']['root']), 2)
        nodes = VersionGraph(self.store.snapshot('tenant')).nodes
        for sid in result['mapping']['summary']:
            self.assertEqual(set(nodes[sid].parents), set(result['mapping']['root']))
        self.assertEqual(len(self.store.context('tenant', 'later')[1]), 2)

    def test_crash_after_stage_resumes_without_repairing_root(self):
        class Crash(BaseException): pass
        def crash(*args): raise Crash()
        self.backend.writers['copy'] = crash
        with self.assertRaises(Crash):
            self.coordinator().recover(self.request)
        self.assertEqual(self.store.job('tenant', 'repair')['state'], 'quarantined')
        self.backend.writers['copy'] = lambda inputs, task: tuple(v.content for v in inputs)
        result = self.coordinator(store=SQLiteRecoveryStore(self.path)).recover(self.request)
        self.assertEqual(result['outcome'], 'ready')
        self.assertEqual(self.cleaner.calls, ['root'])

    def test_crash_after_publication_retries_only_projection(self):
        class Crash(BaseException): pass
        original = self.projection.install
        def crash(manifest): raise Crash()
        self.projection.install = crash
        with self.assertRaises(Crash):
            self.coordinator().recover(self.request)
        first = self.store.job('tenant', 'repair')
        self.assertEqual(first['state'], 'published')
        with self.assertRaisesRegex(RecoveryError, 'scope_blocked'):
            self.store.context('tenant', 'current')
        self.projection.install = original
        second = self.coordinator().recover(self.request)
        self.assertEqual(first['mapping'], second['mapping'])
        self.assertEqual(second['outcome'], 'ready')

    def test_database_failure_rolls_back_whole_publication(self):
        with self.store._tx() as db:
            db.execute("CREATE TRIGGER inject_failure BEFORE INSERT ON recovery_versions WHEN json_extract(NEW.record,'$.artifact_id') = 'artifact/summary' BEGIN SELECT RAISE(ABORT,'injected'); END")
        first = self.coordinator().recover(self.request)
        self.assertEqual(first['error'], 'adapter_failed')
        self.assertEqual(first['state'], 'quarantined')
        snapshot = self.store.snapshot('tenant')
        self.assertEqual(len(snapshot.versions), 4)
        self.assertEqual({v.status for v in snapshot.versions if v.version_id != 'good'}, {'quarantined'})
        with self.store._tx() as db:
            db.execute('DROP TRIGGER inject_failure')
        self.assertEqual(self.coordinator().recover(self.request)['outcome'], 'ready')

    def test_projection_failure_retains_barrier(self):
        self.projection.install = lambda manifest: 'wrong digest'
        result = self.coordinator().recover(self.request)
        self.assertEqual(result['error'], 'projection_not_acknowledged')
        self.assertFalse(self.store.ready('tenant', result['revision']))

    def test_external_graph_mismatch_and_incomplete(self):
        for name, snapshot in [('incomplete_graph', replace(fixture(), coverage='partial')),
                               ('graph_ledger_mismatch', replace(fixture(), revision=1))]:
            with self.subTest(name=name):
                adapter = JSONGraphAdapter(lambda _: snapshot.to_dict())
                # Separate scope for each test via fresh fixture database.
                path = Path(self.tmp.name) / (name + '.db')
                store = SQLiteRecoveryStore(path)
                store.seed(fixture(), {'current': ('summary',)})
                result = self.coordinator(store=store, graph=adapter).recover(replace(self.request, call_id=None))
                self.assertEqual(result['error'], name)

    def test_json_graph_roundtrip(self):
        adapter = JSONGraphAdapter(lambda _: json.loads(canonical(self.store.snapshot('tenant').to_dict())))
        self.assertEqual(self.coordinator(graph=adapter).recover(self.request)['outcome'], 'ready')

    def test_late_alert_revalidates_previous_successors(self):
        first = self.coordinator().recover(self.request)
        second = self.coordinator().recover(replace(self.request, request_id='late', call_id=None))
        self.assertEqual(second['outcome'], 'ready')
        self.assertEqual(set(second['mapping']), {n for ids in first['mapping'].values() for n in ids})

    def test_historical_receipt_not_current_permission(self):
        self.coordinator().recover(self.request)
        self.store.append('tenant', version('extra', 'new fact'), 'current')
        self.assertEqual(self.coordinator().recover(self.request)['error'], 'historical_receipt')

    def test_budget_failure_cannot_bypass_on_retry(self):
        coordinator = self.coordinator(max_nodes=4)
        for _ in range(2):
            result = coordinator.recover(self.request)
            self.assertEqual(result['error'], 'graph_budget_exceeded')
            self.assertEqual(result['state'], 'quarantined')

    def test_backend_error_redacts_sensitive_exception(self):
        def fail(*args): raise ValueError('SECRET CONTENT')
        self.cleaner.repair = fail
        result = self.coordinator().recover(self.request)
        self.assertEqual(result['error'], 'adapter_failed')
        self.assertNotIn('SECRET CONTENT', canonical(result))

    def test_dual_replica_partial_write_recoverable(self):
        class Replica:
            fail = False
            value = None
            def replace_scope(self, manifest):
                if self.fail: raise IOError('offline')
                self.value = manifest
            def digest(self, scope): return self.value['digest'] if self.value else None
        a, b = Replica(), Replica()
        b.fail = True
        projection = DualLabelProjection(a, b, self.projection, configuration_id='fixture/1')
        coordinator = self.coordinator(projection=projection)
        first = coordinator.recover(self.request)
        self.assertEqual(first['outcome'], 'needs_review')
        self.assertIsNotNone(a.value)
        b.fail = False
        second = coordinator.recover(self.request)
        self.assertEqual(second['outcome'], 'ready')
        self.assertEqual(a.value, b.value)
        self.assertEqual(len(a.value['withdrawn']), 3)

    def test_dispatch_requires_fresh_authorization(self):
        self.coordinator().recover(self.request)
        effects = []
        executor = SafeExecutor(self.store, lambda p: None, lambda *args: effects.append(args))
        with self.assertRaisesRegex(RecoveryError, 'authorization_denied'):
            executor.dispatch(self.proposal())
        self.assertEqual(effects, [])

    def test_dispatch_once_and_same_business_operation_cannot_replay(self):
        self.coordinator().recover(self.request)
        effects = []
        executor = SafeExecutor(self.store, self.authorize, lambda *args: effects.append(args) or {'ok': True})
        proposal = self.proposal()
        self.assertEqual(executor.dispatch(proposal), {'ok': True})
        with self.assertRaisesRegex(RecoveryError, 'effect_already_claimed'):
            executor.dispatch(replace(proposal, arguments_json=canonical({'recipient': 'another'})))
        self.assertEqual(len(effects), 1)

    def test_stale_action_cannot_execute_after_recovery(self):
        before = self.proposal()
        self.coordinator().recover(self.request)
        executor = SafeExecutor(self.store, self.authorize, lambda *args: self.fail('executed stale'))
        with self.assertRaisesRegex(RecoveryError, 'stale_or_blocked_action'):
            executor.dispatch(before)

    def test_unknown_effect_blocks_resume_until_reconciled(self):
        def timeout(*args): raise TimeoutError('remote may already have executed')
        executor = SafeExecutor(self.store, self.authorize, timeout)
        with self.assertRaisesRegex(RecoveryError, 'effect_outcome_unknown'):
            executor.dispatch(self.proposal())
        result = self.coordinator().recover(self.request)
        self.assertEqual(result['error'], 'unresolved_effect')
        self.store.reconcile_effect('tenant', 'business-operation', committed=True, evidence='trusted-receipt')
        self.assertEqual(self.coordinator().recover(self.request)['error'], 'affected_committed_effect_requires_review')
        self.store.review_committed_effect('tenant','business-operation','repair',evidence='trusted incident disposition')
        self.assertEqual(self.coordinator().recover(self.request)['outcome'], 'ready')
        with self.assertRaisesRegex(RecoveryError, 'effect_already_claimed'):
            SafeExecutor(self.store, self.authorize, lambda *args: None).dispatch(self.proposal())

    def test_crash_during_effect_stays_in_flight(self):
        class Crash(BaseException): pass
        def crash(*args): raise Crash()
        with self.assertRaises(Crash):
            SafeExecutor(self.store, self.authorize, crash).dispatch(self.proposal())
        self.assertEqual(self.coordinator().recover(self.request)['error'], 'unresolved_effect')

    def test_action_binding_cannot_cross_session(self):
        proposal = self.proposal()
        dormant = next(v for v in fixture().versions if v.version_id == 'dormant')
        proposal = replace(proposal, bindings=((dormant.version_id, dormant.content_sha256),))
        with self.assertRaisesRegex(RecoveryError, 'invalid_action_binding'):
            SafeExecutor(self.store, self.authorize, lambda *args: None).dispatch(proposal)

    def test_revocation_between_authorize_and_claim(self):
        def racing_authorizer(p):
            grant = self.authorize(p)
            self.store.revoke_authorizations(p.scope_id)
            return grant
        with self.assertRaisesRegex(RecoveryError, 'stale_authorization'):
            SafeExecutor(self.store, racing_authorizer, lambda *args: self.fail('executed revoked')).dispatch(self.proposal())

    def test_expired_grant_rejected(self):
        def expired(p): return replace(self.authorize(p), expires_at=time.time() - 1)
        with self.assertRaisesRegex(RecoveryError, 'stale_authorization'):
            SafeExecutor(self.store, expired, lambda *args: None).dispatch(self.proposal())

    def test_consumed_grant_never_revived_by_repair(self):
        def reused(p): return replace(self.authorize(p), grant_id='one-shot')
        executor = SafeExecutor(self.store, reused, lambda *args: {'ok': True})
        executor.dispatch(self.proposal())
        self.assertEqual(self.coordinator().recover(self.request)['error'], 'affected_committed_effect_requires_review')
        self.store.review_committed_effect('tenant','business-operation','repair',evidence='trusted incident disposition')
        self.assertEqual(self.coordinator().recover(self.request)['outcome'], 'ready')
        with self.assertRaisesRegex(RecoveryError, 'authorization_consumed'):
            executor.dispatch(self.proposal(op='different-operation'))

    def test_unknown_effect_blocks_new_business_operation(self):
        def fail(*args): raise TimeoutError()
        executor = SafeExecutor(self.store,self.authorize,fail)
        with self.assertRaisesRegex(RecoveryError,'effect_outcome_unknown'):
            executor.dispatch(self.proposal())
        with self.assertRaisesRegex(RecoveryError,'unresolved_effect'):
            executor.dispatch(self.proposal(op='different-operation'))
        self.assertFalse(self.store.ready('tenant',0))

    def test_unaffected_committed_effect_does_not_block_recovery(self):
        good = fixture().versions[-1]
        proposal = replace(self.proposal(), bindings=((good.version_id, good.content_sha256),))
        SafeExecutor(self.store,self.authorize,lambda *args: {'ok':True}).dispatch(proposal)
        self.assertEqual(self.coordinator().recover(self.request)['outcome'], 'ready')


class GraphValidationTests(unittest.TestCase):
    def test_reachability_backend_receives_only_selected_edge_kinds(self):
        class Backend:
            identity = 'fixture-graph/1'
            def closure(self, nodes, edges, roots, *, reverse=False):
                self.call = (set(nodes), set(edges), roots, reverse)
                return {'root', 'summary'}
        backend = Backend()
        snapshot = replace(
            fixture(),
            edges=fixture().edges + (Edge('good', 'summary', 'supports'),),
        )
        result = VersionGraph(snapshot, reachability=backend).closure(('root',))
        self.assertEqual(result, {'root', 'summary'})
        self.assertEqual(backend.call[2:], (('root',), False))
        self.assertNotIn(Edge('good', 'summary', 'supports'), backend.call[1])

    def test_event_projection_keeps_ephemeral_path(self):
        vs = tuple(version(n,'fact') for n in ('root','temporary','memory','other'))
        events = (CapturedWriterEvent('e1',('root',),('temporary',)), CapturedWriterEvent('e2',('temporary',),('memory',),'copy'))
        snap = snapshot_from_events('s',0,vs,events,coverage='complete_within_scope')
        self.assertEqual(VersionGraph(snap).closure(('root',)), {'root','temporary','memory'})

    def test_event_projection_rejects_omitted_input(self):
        with self.assertRaisesRegex(RecoveryError, 'incomplete_event'):
            snapshot_from_events('s',0,(version('a','fact'),),
                (CapturedWriterEvent('e',('missing',),('a',)),),coverage='complete_within_scope')

    def test_event_projection_rejects_multiple_producers(self):
        with self.assertRaisesRegex(RecoveryError, 'multiple_version_producers'):
            snapshot_from_events('s',0,(version('a','fact'),),
                (CapturedWriterEvent('e1',(),('a',)),CapturedWriterEvent('e2',(),('a',))),coverage='complete_within_scope')
    def test_missing_edge_rejected(self):
        with self.assertRaisesRegex(RecoveryError, 'missing_parent_edge'):
            VersionGraph(replace(fixture(), edges=()))

    def test_unknown_endpoint_rejected(self):
        with self.assertRaisesRegex(RecoveryError, 'missing_edge_endpoint'):
            VersionGraph(replace(fixture(), edges=fixture().edges + (Edge('missing', 'root'),)))

    def test_cycle_rejected(self):
        a = version('a', 'fact', ('b',))
        b = version('b', 'fact', ('a',))
        with self.assertRaisesRegex(RecoveryError, 'cycle_detected'):
            VersionGraph(Snapshot('s', 0, (a,b), (Edge('a','b'),Edge('b','a'))))

    def test_tampered_content_rejected(self):
        with self.assertRaisesRegex(RecoveryError, 'hash_mismatch'):
            replace(fixture().versions[0], content='tampered')

    def test_origin_downgrade_rejected(self):
        vs = list(fixture().versions)
        vs[1] = replace(vs[1], origins=('user',))
        with self.assertRaisesRegex(RecoveryError, 'origin_downgrade'):
            VersionGraph(replace(fixture(), versions=tuple(vs)))

    def test_strings_not_arrays(self):
        data = fixture().to_dict()
        data['versions'][0]['origins'] = 'external'
        with self.assertRaisesRegex(RecoveryError, 'invalid_version_payload'):
            Snapshot.from_dict(data)

    def test_support_does_not_grant_trust_or_cut_dependency(self):
        graph = VersionGraph(replace(fixture(), edges=fixture().edges + (Edge('good','summary','supports'),)))
        self.assertEqual(graph.closure(('root',)), {'root','summary','dormant'})

    def test_bool_revision_rejected(self):
        with self.assertRaisesRegex(RecoveryError, 'invalid_revision'):
            VersionGraph(replace(fixture(), revision=True))


class ModelAdapterTests(unittest.TestCase):
    def test_requires_strict_boolean_and_redetection(self):
        class Client:
            answers = []
            def json(self, *args): return self.answers.pop(0)
        client = Client()
        validator = ModelRepairValidator(client, configuration_id='mock')
        client.answers = [{'safe': 'true', 'faithful': True}]
        self.assertFalse(validator.validate(fixture().versions[0], ('fact',), 'task').accepted())
        client.answers = [{'safe':True,'faithful':True,'reason':'retained'}, {'verdict':'unknown','evidence':[]}]
        self.assertFalse(validator.validate(fixture().versions[0], ('fact',), 'task').accepted())
        client.answers = [{'safe':True,'faithful':True,'reason':'retained'}, {'verdict':'clean','evidence':[]}]
        self.assertTrue(validator.validate(fixture().versions[0], ('fact',), 'task').accepted())

    def test_invalid_model_shape_rejected(self):
        class Client:
            def json(self,*args): return {'outputs': 'fact'}
        with self.assertRaisesRegex(RecoveryError, 'invalid_replacement'):
            ModelRepairBackend(Client(), configuration_id='mock').repair(fixture().versions[0], (), 'task')


if __name__ == '__main__':
    unittest.main()
