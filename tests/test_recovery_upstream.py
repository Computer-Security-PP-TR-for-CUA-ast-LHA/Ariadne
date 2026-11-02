"""Opt-in actual upstream execution; skipped unless pinned checkout is supplied."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import unittest

from cua_guard.recovery.contracts import RecoveryError
from cua_guard.recovery.tma import TMAParameterRecovery
from cua_guard.recovery.srr import SRRNativePlanner


@unittest.skipUnless(os.environ.get('ARIADNE_TMA_CHECKOUT'), 'set ARIADNE_TMA_CHECKOUT for real upstream tests')
class TMAUpstreamTests(unittest.TestCase):
    def setUp(self):
        self.adapter = TMAParameterRecovery(os.environ['ARIADNE_TMA_CHECKOUT'])
        self.authorities = {name: {'domain': name, 'key_hex': (name * 32).encode().hex(),
                                  'scopes': [['send', 'task', 'recipient']]} for name in ('a','b')}
        self.records = [self.packet(n, 'approved') for n in ('a','b')]

    def packet(self, channel, value, until=200):
        record = dict(operation='send', subject='task', field='recipient', value=value,
                      valid_from=0, valid_until=until, endorsed=True)
        body = json.dumps(record, sort_keys=True, separators=(',', ':'))
        return {'channel': channel, 'body': body, 'signature': hmac.new(
            bytes.fromhex(self.authorities[channel]['key_hex']), body.encode(), hashlib.sha256).hexdigest()}

    def call(self, **changes):
        args = dict(authorities=self.authorities, policy={'send':['recipient']}, records=self.records,
                    operation='send', subject='task', now=100)
        return self.adapter.recover_parameters(**{**args, **changes})

    def test_original_code_recovers_unique_parameter(self):
        self.assertEqual(self.call(), {'status':'available','subject':'task','fields':{'recipient':'approved'}})

    def test_single_domain_not_two_independent_endorsements(self):
        self.authorities['b']['domain'] = 'a'
        self.assertEqual(self.call()['status'], 'unavailable')

    def test_revoked_channel_not_authority(self):
        self.assertEqual(self.call(revoked=['a'])['status'], 'unavailable')

    def test_expired_records_not_authority(self):
        self.assertEqual(self.call(now=201)['status'], 'unavailable')

    def test_ambiguous_parameters_fail_closed(self):
        self.records += [self.packet(n,'other') for n in ('a','b')]
        self.assertEqual(self.call()['status'], 'ambiguous')

    def test_forged_signature_rejected(self):
        self.records[0]['signature'] = '0' * 64
        self.assertEqual(self.call()['status'], 'unavailable')

    def test_wrong_subject_not_authority(self):
        self.assertEqual(self.call(subject='other-task')['status'], 'unavailable')

    def test_wrong_source_bytes_cannot_load(self):
        with tempfile.TemporaryDirectory() as path:
            (Path(path) / 'code').mkdir()
            (Path(path) / 'code/scoped_authorization.py').write_text('raise Exception("fake")')
            with self.assertRaisesRegex(RecoveryError, 'authority_backend_rejected'):
                TMAParameterRecovery(path).recover_parameters(authorities={}, policy={}, records=[], operation='send', subject='task', now=1)


@unittest.skipUnless(os.environ.get('ARIADNE_SRR_CHECKOUT'), 'set ARIADNE_SRR_CHECKOUT for real upstream tests')
class SRRUpstreamTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        (self.path / 'checkpoints').mkdir()
        self.objects = [self.obj('user','user_turn',[]), self.obj('root','tool_result',[]),
                        self.obj('intermediate','tool_result',['root']),
                        self.obj('memory','memory',['user','intermediate'], {'produced_by_event_id':'event1'})]
        self.events = [dict(event_id='event1',run_id='fixture',session_id='s2',type='memory_write',
                            input_object_ids=['user','intermediate'],output_object_ids=['memory'],meta={})]
        self.adapter = SRRNativePlanner(os.environ['ARIADNE_SRR_CHECKOUT'])

    def obj(self, oid, kind, parents, meta=None):
        return dict(object_id=oid,run_id='fixture',session_id='s2',kind=kind,subkind='',content='fixture',
                    source='fixture',parent_ids=parents,status='active',meta=meta or {})

    def call(self, roots=('root',)):
        (self.path / 'objects.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in self.objects), encoding='utf-8')
        (self.path / 'events.jsonl').write_text(''.join(json.dumps(v)+'\n' for v in self.events), encoding='utf-8')
        return self.adapter.plan(self.path, roots)

    def test_original_closure_traverses_ephemeral_bridge(self):
        plan = self.call()
        self.assertEqual(plan['revoked_object_ids'], ['memory'])
        self.assertEqual(plan['mode'], 'writer_only')
        self.assertEqual(plan['replay_order'], ['event1'])

    def test_original_unsafe_writer_fallback(self):
        self.events[0]['input_object_ids'] = ['root']
        self.assertEqual(self.call()['mode'], 'coarse_rollback')

    def test_adapter_rejects_unknown_root_before_original(self):
        with self.assertRaisesRegex(RecoveryError, 'srr_backend_rejected'):
            self.call(('missing',))


if __name__ == '__main__':
    unittest.main()
