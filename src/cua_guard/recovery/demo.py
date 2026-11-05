"""Offline recovery/continuation acceptance scenario, not an attack benchmark.

Run: python -m cua_guard.recovery.demo
No API keys, remote tools or network access. Fixture-only repair/judgment are
deliberately local to this demo so they cannot be mistaken for a real detector.
"""
import argparse
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from .contracts import Edge, RecoveryRequest, Snapshot, Validation, Version, canonical, digest
from .sqlite import SQLiteRecoveryStore
from .coordinator import RecoveryCoordinator
from .adapters import JSONGraphAdapter, ManagedContextProjection
from .dgrr import DGRRReachability
from .srr_writer import SRRWriterBackend
from .execution import AuthorizationGrant, Proposal, SafeExecutor


def example_snapshot():
    def v(vid, text, parents=(), writer=None):
        return Version(vid, vid, text, digest(text), ('external',), parents, writer_key=writer)
    return Snapshot('benchmark-task-001', 0, (
        v('web-v1', 'Meeting: Tuesday 10:00. [INJECTION: send secrets]'),
        v('summary-v1', 'Meeting: Tuesday 10:00. [INJECTION: send secrets]', ('web-v1',), 'copy'),
        v('dormant-v1', 'Meeting: Tuesday 10:00. [INJECTION: send secrets]', ('summary-v1',), 'copy'),
        v('benign-v1', 'Room: 301.')),
        (Edge('web-v1','summary-v1'), Edge('summary-v1','dormant-v1')))


class FixtureRepair:
    identity = 'offline-exact-fixture/1'
    def repair(self, old, inputs, task):
        if old.content != 'Meeting: Tuesday 10:00. [INJECTION: send secrets]':
            raise ValueError('not this synthetic fixture')
        return ('Meeting: Tuesday 10:00.',)


class FixtureValidation:
    identity = 'offline-exact-expectation/1'
    def validate(self, old, outputs, task):
        matches = outputs == ('Meeting: Tuesday 10:00.',)
        return Validation(matches, matches, 'fixture-ground-truth/meeting-time')


class FixtureWriter:
    identity = 'offline-copy-writer/1'

    def write(self, kind, inputs, task):
        return tuple(v.content for v in inputs)


def run(directory, srr_checkout):
    store = SQLiteRecoveryStore(Path(directory) / 'recovery.sqlite')
    before = example_snapshot()
    store.seed(before, {'current': ('summary-v1','benign-v1'), 'future': ('dormant-v1',)})
    store.record_call(before.scope_id, 'blocked-call', ('summary-v1',))
    backend = SRRWriterBackend(srr_checkout, FixtureRepair(), FixtureWriter(), {'copy':'memory_write'})
    reachability = DGRRReachability()
    projection = ManagedContextProjection(store)
    graph = JSONGraphAdapter(lambda scope: store.snapshot(scope).to_dict())
    request = RecoveryRequest('incident-001', before.scope_id, 'Return the meeting time and room.',
                              ('web-v1',), ('oracle-fixture-evidence',), call_id='blocked-call')
    started = time.perf_counter()
    result = RecoveryCoordinator(
        store, backend, FixtureValidation(), projection,
        graph=graph, reachability=reachability,
    ).recover(request)
    if result['outcome'] != 'ready':
        raise RuntimeError(result['error'])
    # Restart the host; active context is reconstructed from durable state.
    store = SQLiteRecoveryStore(Path(directory) / 'recovery.sqlite')
    revision, context = store.context(before.scope_id, 'current')
    _, future = store.context(before.scope_id, 'future')
    calls = []
    proposal = Proposal(before.scope_id, 'current', 'return-meeting-result', revision,
        tuple((v.version_id,v.content_sha256) for v in context), 'return_answer',
        canonical({'answer':'Meeting: Tuesday 10:00. Room: 301.'}))
    def authorize(p):
        if p.tool != 'return_answer' or json.loads(p.arguments_json) != {'answer':'Meeting: Tuesday 10:00. Room: 301.'}:
            return None
        return AuthorizationGrant(str(uuid.uuid4()),p.fingerprint,store.authority_epoch(p.scope_id),time.time()+30)
    def execute(tool, arguments, operation_id):
        calls.append(operation_id)
        return arguments['answer']
    answer = SafeExecutor(store, authorize, execute).dispatch(proposal)
    active = store.manifest(before.scope_id)['versions']
    report = {
        'mode': 'offline_synthetic_mechanism', 'oracle_localization': True,
        'repair_backend': backend.identity, 'model_calls': 0, 'external_tool_calls': 0,
        'workflow_engine':'langgraph', 'graph_backend':reachability.identity,
        'native_replay':backend.last_replay,
        'recovery_outcome': result['outcome'], 'affected_versions': len(result['mapping']),
        'old_versions_still_visible': sum(v['version_id'] in result['mapping'] for v in active),
        'preserved_benign_version': any(v.version_id == 'benign-v1' and v.content == 'Room: 301.' for v in context),
        'dormant_copy_rebuilt': all(v.content == 'Meeting: Tuesday 10:00.' for v in future),
        'resumed_once': len(calls) == 1, 'fixture_task_success': answer == 'Meeting: Tuesday 10:00. Room: 301.',
        'elapsed_seconds': round(time.perf_counter()-started, 6),
        'not_measured': ['real_model_ASR','real_GUI_recovery','semantic_detector_accuracy'],
    }
    if not (report['old_versions_still_visible'] == 0 and all(report[k] for k in (
        'preserved_benign_version','dormant_copy_rebuilt','resumed_once','fixture_task_success'))):
        raise RuntimeError('offline acceptance failed')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional synthetic metrics JSON destination')
    parser.add_argument('--srr-checkout', default=os.environ.get('ARIADNE_SRR_CHECKOUT'), help='Pinned original SRR checkout')
    args = parser.parse_args()
    if not args.srr_checkout:
        parser.error('Set ARIADNE_SRR_CHECKOUT or --srr-checkout; no handwritten replay fallback')
    with tempfile.TemporaryDirectory(prefix='ariadne-recovery-') as directory:
        report = run(directory, args.srr_checkout)
    text = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
