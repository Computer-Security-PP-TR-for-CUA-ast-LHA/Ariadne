"""Upstream StateGraph + SqliteSaver own scheduling, checkpoints and interrupts.

Domain SQL remains the authority for publication, barriers and non-rewindable
effects. A graph checkpoint is never permission to publish/execute by itself.
"""
from contextlib import closing
import sqlite3
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .contracts import RecoveryError, digest


class RecoveryState(TypedDict, total=False):
    job: dict
    error: str | None
    retry_node: str
    manifest_digest: str


def invoke_recovery(coordinator, request):
    store = coordinator.store

    def latest():
        return store.job(request.scope_id, request.request_id)

    def summary(job):
        # Source text, model outputs and task content stay in the domain ledger.
        # Do not duplicate an ever-growing staged blob in every checkpoint.
        return {k:job[k] for k in ('scope_id','request_id','revision','state','fingerprint')} | {
            'target_count':len(job['plan']['targets']) if job['plan'] else 0,
            'staged_count':len(job['staged'])}

    def guarded(name, operation):
        def run(state):
            try:
                result = operation(state)
                if 'job' in result:
                    result['job'] = summary(result['job'])
                return {**result, 'error': None}
            except Exception as exc:
                code = exc.code if isinstance(exc, RecoveryError) else 'adapter_failed'
                return {'job':summary(store.fail(request, code)), 'error':code, 'retry_node':name}
        return run

    def publish(state):
        job = latest()
        return {'job':store.publish(request) if job['state'] == 'quarantined' else job}

    def install(state):
        job = latest()
        if job['state'] == 'ready':
            return {'job':job}
        manifest = store.manifest(request.scope_id)
        if manifest['revision'] != job['revision']:
            raise RecoveryError('revision_conflict')
        # One durable node includes BOTH install and acknowledgment. A restart in
        # between must reinstall volatile host state, not replay a cached ACK.
        acknowledgment = coordinator.projection.install(manifest)
        return {'job':store.acknowledge(request, acknowledgment),'manifest_digest':acknowledgment}

    def review(state):
        # A separate durable task avoids mixing successive failed attempts into
        # the same positional interrupt/resume history.
        interrupt({'request_id':request.request_id,'error':state['error']})
        return {'error':None}

    graph = StateGraph(RecoveryState)
    graph.add_node('prepare', guarded('prepare', lambda _: {'job':coordinator.prepare(request)}))
    graph.add_node('repair', guarded('repair', lambda _: {'job':coordinator.repair_one(request)}))
    graph.add_node('publish', guarded('publish', publish))
    graph.add_node('install', guarded('install', install))
    graph.add_node('review', review)
    graph.add_edge(START, 'prepare')
    graph.add_conditional_edges('prepare', lambda s:'review' if s.get('error') else 'repair')
    graph.add_conditional_edges('repair', lambda s:'review' if s.get('error') else (
        'repair' if s['job']['staged_count'] != s['job']['target_count'] else 'publish'))
    graph.add_conditional_edges('publish', lambda s:'review' if s.get('error') else 'install')
    graph.add_conditional_edges('install', lambda s:'review' if s.get('error') else END)
    graph.add_conditional_edges('review', lambda s:s['retry_node'])
    # One journal per scope; the upstream file lock fences writers. This is a
    # local runtime, not a distributed saver/fencing configuration.
    path = store.workflow_path(request.scope_id)
    with closing(sqlite3.connect(path, check_same_thread=False, timeout=15)) as connection:
        connection.execute('PRAGMA synchronous=FULL')
        saver = SqliteSaver(connection, serde=JsonPlusSerializer(
            pickle_fallback=False, allowed_json_modules=None, allowed_msgpack_modules=None))
        compiled = graph.compile(checkpointer=saver)
        config = {'configurable': {'thread_id':digest(request.request_id)},
                  'recursion_limit':coordinator.max_nodes * 2 + 32}
        previous = compiled.get_state(config)
        if previous.values and not previous.next and latest()['state'] == 'ready':
            return {**latest(),'outcome':'ready'}
        if previous.values and (previous.values['job']['fingerprint'] != latest()['fingerprint'] or not previous.next):
            job = store.fail(request,'workflow_domain_divergence')
            return {**job,'outcome':'needs_review'}
        payload = ({'job':summary(latest()),'error':None} if not previous.values else
                   Command(resume=True) if any(t.interrupts for t in previous.tasks) else None)
        compiled.invoke(payload, config, durability='sync')
    job = latest()
    return {**job,'outcome':'ready' if job['state'] == 'ready' else 'needs_review'}
