"""Integration with real upstream replay and durable workflow checkpoints."""
from dataclasses import replace
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from cua_guard.recovery import RecoveryCoordinator, SQLiteRecoveryStore
from cua_guard.recovery.adapters import ManagedContextProjection
from cua_guard.recovery.contracts import RecoveryError
from cua_guard.recovery.srr_writer import SRRWriterBackend
from test_recovery import fixture, FixtureBackend, FixtureValidator, RecoveryRequest


class Provider:
    identity = 'integration-pure-provider/1'
    def __init__(self):
        self.calls = []
        self.outputs = None
    def write(self, kind, inputs, task):
        self.calls.append((kind,inputs,task))
        return self.outputs if self.outputs is not None else tuple(v.content for v in inputs)


@unittest.skipUnless(os.environ.get('ARIADNE_SRR_CHECKOUT'), 'real pinned SRR checkout required')
class ReusedRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = SQLiteRecoveryStore(Path(self.tmp.name)/'domain.sqlite')
        self.store.seed(fixture(), {'current':('summary','good'),'later':('dormant',)})
        self.cleaner, self.provider = FixtureBackend(), Provider()
        self.backend = SRRWriterBackend(os.environ['ARIADNE_SRR_CHECKOUT'],self.cleaner,self.provider,{'copy':'memory_write'})
        self.projection = ManagedContextProjection(self.store)
        self.coordinator = RecoveryCoordinator(self.store,self.backend,FixtureValidator(),self.projection)
        self.request = RecoveryRequest('r','tenant','Use fact',('root',),('evidence',))

    def test_original_replayer_is_in_default_recovery_path(self):
        result = self.coordinator.recover(self.request)
        self.assertEqual(result['outcome'],'ready')
        self.assertEqual(len(self.provider.calls),2)
        self.assertEqual(self.backend.last_replay['function'],'replay_dirty_writers')
        self.assertEqual(self.backend.last_replay['old_status'],'replaced')
        for _,inputs,_ in self.provider.calls:
            self.assertTrue(all(v.content == 'fact' for v in inputs))
        self.assertEqual(self.store.context('tenant','later')[1][0].content,'fact')
        with closing(sqlite3.connect(self.store.workflow_path('tenant'))) as db:
            self.assertGreater(db.execute('SELECT COUNT(*) FROM checkpoints').fetchone()[0],3)

    def test_one_to_many_preserves_outputs_despite_upstream_scalar_map(self):
        self.provider.outputs = ('fact A','fact B')
        result = self.coordinator.recover(self.request)
        self.assertEqual(result['outcome'],'ready')
        self.assertEqual(len(result['mapping']['summary']),2)
        self.assertEqual(len(result['mapping']['dormant']),2)
        self.assertEqual(self.backend.last_replay['new_object_count'],2)
        self.assertEqual(self.backend.last_replay['scalar_mapping_size'],1)
        self.assertEqual({v.content for v in self.provider.calls[-1][1]},{'fact A','fact B'})

    def test_native_summary_writer(self):
        self.backend.recipes['copy']='summary_write'
        result = self.coordinator.recover(self.request)
        self.assertEqual(result['outcome'],'ready')
        self.assertEqual({call[0] for call in self.provider.calls},{'summary_write'})

    def test_invalid_writer_output_stays_quarantined(self):
        self.provider.outputs=()
        result=self.coordinator.recover(self.request)
        self.assertEqual(result['error'],'invalid_replacement')
        self.assertEqual(len(self.store.snapshot('tenant').versions),4)

    def test_changed_recipe_cannot_resume_old_request(self):
        self.provider.outputs=()
        self.assertEqual(self.coordinator.recover(self.request)['outcome'],'needs_review')
        self.backend.recipes['copy']='summary_write'
        with self.assertRaises(RecoveryError) as caught:
            self.coordinator.recover(self.request)
        self.assertEqual(caught.exception.code,'request_id_conflict')

    def test_missing_upstream_has_no_handwritten_fallback(self):
        self.backend.checkout=self.tmp.name
        result=self.coordinator.recover(self.request)
        self.assertEqual(result['outcome'],'needs_review')
        self.assertEqual(self.provider.calls,[])

    def test_restart_after_review_uses_checkpoints_and_no_duplicate_writers(self):
        self.projection.install=lambda manifest: 'wrong'
        self.assertEqual(self.coordinator.recover(self.request)['outcome'],'needs_review')
        # Distinct adapter instances emulate host restart; no checkpoint pickle.
        store=SQLiteRecoveryStore(self.store.path)
        new=RecoveryCoordinator(store,self.backend,FixtureValidator(),ManagedContextProjection(store))
        self.assertEqual(new.recover(self.request)['outcome'],'ready')
        self.assertEqual(len(self.provider.calls),2)
        self.assertEqual(new.recover(self.request)['outcome'],'ready')
        self.assertEqual(len(self.provider.calls),2)

    def test_repeated_failed_reviews_retry_only_once_per_call(self):
        self.provider.outputs=()
        for expected in (1,2,3):
            self.assertEqual(self.coordinator.recover(self.request)['outcome'],'needs_review')
            self.assertEqual(len(self.provider.calls),expected)
        self.provider.outputs=None
        self.assertEqual(self.coordinator.recover(self.request)['outcome'],'ready')

    def test_disallowed_external_effect_recipe(self):
        with self.assertRaises(ValueError):
            SRRWriterBackend(os.environ['ARIADNE_SRR_CHECKOUT'],self.cleaner,self.provider,{'send':'external_effect'})

    def test_actual_process_death_between_domain_commit_and_graph_checkpoint(self):
        script=Path(__file__).with_name('recovery_process_fixture.py')
        for phase in ('stage','publish','install','acknowledge'):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                command=[sys.executable,str(script),directory,phase]
                first=subprocess.run(command,capture_output=True,timeout=60)
                self.assertEqual(first.returncode,77,first.stderr.decode(errors='replace'))
                (root/'crashed').touch()
                second=subprocess.run(command,capture_output=True,timeout=60)
                self.assertEqual(second.returncode,0,second.stderr.decode(errors='replace'))
                self.assertEqual((root/'root-calls').read_text().splitlines(),['root'])
                # The install callback is idempotently rerun after a crash, not
                # bypassed by a cached 'installed' result from a dead host.
                if phase=='install':
                    self.assertEqual(len((root/'install-calls').read_text().splitlines()),2)


if __name__=='__main__':
    unittest.main()
