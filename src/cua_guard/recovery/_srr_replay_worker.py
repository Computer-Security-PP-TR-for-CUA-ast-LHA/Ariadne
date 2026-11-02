"""Standalone native SRR replay worker. Never calls tools or coarse rollback."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

PIN = 'd7bcb32740156cb985fae0ee93caba35ee45e67e'


def receive():
    line = sys.stdin.buffer.readline(4_000_001)
    if len(line) > 4_000_000:
        raise ValueError('input budget exceeded')
    return json.loads(line)


def emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


def main():
    root = Path(sys.argv[1]).resolve()
    def git(*args):
        return subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True,
                              encoding='utf-8',timeout=10).stdout.strip()
    if git('rev-parse','HEAD') != PIN or git('status','--porcelain','--untracked-files=all','--','src'):
        raise ValueError('unqualified checkout')
    sys.path.insert(0,str(root))
    from src.store import RunRegistry
    from src.schemas import ObjectRecord, EventRecord
    from src.recover import build_replay_plan, replay_dirty_writers
    request = receive()
    if request['kind'] not in {'memory_write','summary_write'}:
        raise ValueError('not a pure writer')

    class Backend:
        def exchange(self, kind, user_turn, tool_results):
            emit({'type':'writer','kind':kind,'task':user_turn,
                  'inputs':[{'id':v.meta['ariadne_id'],'content':v.content} for v in tool_results]})
            result = receive()['outputs']
            if not isinstance(result,list) or not 1 <= len(result) <= 16 or any(not isinstance(v,str) for v in result):
                raise ValueError('invalid outputs')
            return result

        def write_memory(self, chain, session_id, user_turn, tool_results, answer_text):
            return {'items':[{'text':v,'kind':'ariadne_repair'} for v in self.exchange('memory_write',user_turn,tool_results)]}

        def write_summary(self, chain, session_id, previous_summary, user_turn, tool_results, answer_text):
            outputs = self.exchange('summary_write',user_turn,tool_results)
            if len(outputs) != 1:
                raise ValueError('summary requires one output')
            return {'summary':outputs[0],'carry_forward':[]}

    with tempfile.TemporaryDirectory(prefix='ariadne-srr-') as directory:
        registry = RunRegistry(directory)
        def obj(oid, kind, content, parents, meta):
            return ObjectRecord(oid,'ariadne','s2',kind,'',content,'host',parents,'active',meta)
        # Opaque native IDs avoid collisions with arbitrary caller version IDs.
        registry.append_object(obj('user','user_turn',request['task'],[],{}))
        ids = []
        for index, version in enumerate(request['inputs']):
            oid = 'input_' + str(index)
            ids.append(oid)
            registry.append_object(obj(oid,'tool_result',version['content'],[],{'ariadne_id':version['version_id']}))
        kind = 'memory' if request['kind'] == 'memory_write' else 'summary'
        registry.append_object(obj('old',kind,'[withheld polluted output]',['user',*ids],
                                   {'memory_kind':'ariadne_repair','produced_by_event_id':'writer'}))
        registry.append_event(EventRecord('writer','ariadne','s2',request['kind'],['user',*ids],['old'],{}))
        plan = build_replay_plan(registry,'input','recovery',[],['old'])
        if plan.mode != 'writer_only':
            raise ValueError('not safely replayable')
        replay_dirty_writers(registry,Backend(),None,'retrieval','recovery',plan,
                             {'memory_writer':'ariadne/1','summary_writer':'ariadne/1'})
        events = [e for e in registry.events if e.meta.get('replay_of') == 'writer']
        if len(events) != 1:
            raise ValueError('invalid replay event')
        replacements = [registry.get_object(oid) for oid in events[0].output_object_ids]
        if not replacements or any(v.meta.get('replay_of') != 'old' or set(v.parent_ids) != {'user',*ids} for v in replacements):
            raise ValueError('invalid replay lineage')
        # Upstream's scalar replacement_map overwrites one-to-many mappings.
        # Enumerate the authoritative replay event outputs instead; retain ALL.
        emit({'type':'result','outputs':[v.content for v in replacements],
              'audit':{'upstream_commit':PIN,'function':'replay_dirty_writers',
                       'native_event_count':len(events),'new_object_count':len(replacements),
                       'scalar_mapping_size':len(plan.replacement_map),'old_status':registry.get_object('old').status}})


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.stderr.write('SRR replay failed\n')
        sys.exit(1)
