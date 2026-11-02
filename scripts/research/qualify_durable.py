"""Comparable real-process crash probes for upstream workflow engines (no models).

Install the exact candidate versions from docs/recovery/reuse-audit.lock.json.
Run with --engine dbos or langgraph; the default parent checks actual process death,
restart and a repeated completed request. This is not a throughput benchmark.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def record(directory, step):
    path = Path(directory) / (step + '.txt')
    with path.open('a', encoding='utf-8') as stream:
        stream.write('called\n')
        stream.flush()
        os.fsync(stream.fileno())


def execute(engine, directory):
    if engine == 'dbos':
        from dbos import DBOS, SetWorkflowID

        @DBOS.step()
        def first(directory):
            record(directory, 'first')
            return 'retained'

        @DBOS.step()
        def second(directory, value):
            record(directory, 'second')
            if (Path(directory) / 'crash').exists():
                os._exit(77)
            return value + '/finished'

        @DBOS.workflow()
        def flow(directory):
            return second(directory, first(directory))

        DBOS(config={'name': 'ariadne-qualification', 'application_version': 'probe/1',
                     'system_database_url': 'sqlite:///' + str(Path(directory) / 'dbos.sqlite'),
                     'enable_otlp': False, 'log_level': 'ERROR',
                     'notification_listener_polling_interval_sec': 0.05})
        DBOS.launch()
        try:
            with SetWorkflowID('fixed-probe'):
                result = flow(directory)
            assert result == 'retained/finished'
        finally:
            DBOS.destroy()
    else:
        from typing import TypedDict
        from langgraph.graph import StateGraph, START, END
        from langgraph.checkpoint.sqlite import SqliteSaver

        class State(TypedDict):
            directory: str
            value: str

        def first(state):
            record(state['directory'], 'first')
            return {'value': 'retained'}

        def second(state):
            record(state['directory'], 'second')
            if (Path(state['directory']) / 'crash').exists():
                os._exit(77)
            return {'value': state['value'] + '/finished'}

        builder = StateGraph(State)
        builder.add_node('first', first)
        builder.add_node('second', second)
        builder.add_edge(START, 'first')
        builder.add_edge('first', 'second')
        builder.add_edge('second', END)
        with SqliteSaver.from_conn_string(str(Path(directory) / 'graph.sqlite')) as saver:
            graph = builder.compile(checkpointer=saver)
            config = {'configurable': {'thread_id': 'fixed-probe'}}
            previous = graph.get_state(config)
            result = graph.invoke(None if previous.values else {'directory':directory,'value':''},
                                  config, durability='sync')
            assert result['value'] == 'retained/finished'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', required=True, choices=['dbos','langgraph'])
    parser.add_argument('--child', type=Path)
    args = parser.parse_args()
    if args.child:
        execute(args.engine, str(args.child))
        return
    with tempfile.TemporaryDirectory(prefix='ariadne-engine-') as directory:
        root = Path(directory)
        (root / 'crash').touch()
        command = [sys.executable, str(Path(__file__).resolve()), '--engine', args.engine, '--child',directory]
        first = subprocess.run(command, capture_output=True, timeout=45)
        if first.returncode != 77:
            raise RuntimeError(first.stderr.decode('utf-8', errors='replace'))
        (root / 'crash').unlink()
        for _ in range(2):
            completed = subprocess.run(command, capture_output=True, timeout=45)
            if completed.returncode:
                raise RuntimeError(completed.stderr.decode('utf-8', errors='replace'))
        counts = {step: len((root / (step+'.txt')).read_text().splitlines()) for step in ('first','second')}
        assert counts == {'first':1,'second':2}, counts
        print(json.dumps({'engine':args.engine,'completed_step_calls':counts['first'],
                          'interrupted_step_calls':counts['second'],'crash_exit':77,
                          'restart_and_completed_request_replay':'passed','model_calls':0}))


if __name__ == '__main__':
    main()
