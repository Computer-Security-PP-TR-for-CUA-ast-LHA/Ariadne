"""Record inspected checkouts and installed dependency versions; no execution claims."""
import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import subprocess
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstreams',type=Path,required=True)
    parser.add_argument('--install-report',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    seen={}
    queue=[(name,set()) for name in ['langgraph','langgraph-checkpoint','langgraph-checkpoint-sqlite','filelock','PyYAML','Jinja2']]
    env=default_environment()
    while queue:
        name,extras=queue.pop()
        key=canonicalize_name(name)
        if key in seen: continue
        dist=metadata.distribution(name)
        seen[key]={'version':dist.version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License'),
                   'requires_python':dist.metadata.get('Requires-Python')}
        for raw in dist.requires or []:
            req=Requirement(raw)
            if req.marker is None or any(req.marker.evaluate({**env,'extra':e}) for e in extras|{''}):
                queue.append((req.name,set(req.extras)))
    report=json.loads(args.install_report.read_text(encoding='utf-8'))
    artifacts={canonicalize_name(x['metadata']['name']):x['download_info']['archive_info']['hashes']['sha256'] for x in report['install']}
    for name,info in seen.items(): info['tested_wheel_sha256']=artifacts.get(name)
    files={
        'langgraph':['libs/langgraph/LICENSE','libs/langgraph/langgraph/pregel/_loop.py','libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/__init__.py','libs/checkpoint/langgraph/checkpoint/serde/jsonplus.py'],
        'dbos-transact-py':['LICENSE','dbos/_core.py','dbos/_recovery.py','dbos/_sys_db_sqlite.py'],
        'selective-revocation-replay':['src/recover.py','src/store.py','src/schemas.py','src/ids.py'],
    }
    sources={repo:{'commit':subprocess.check_output(['git','-C',str(args.upstreams/repo),'rev-parse','HEAD'],text=True).strip(),
                   'normalized_file_sha256':{name:hashlib.sha256((args.upstreams/repo/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest() for name in names}}
             for repo,names in files.items()}
    target=root/'docs/recovery/reuse-audit.lock.json'
    existing=json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    existing.update(runtime_packages=dict(sorted(seen.items())),sources=sources)
    target.write_text(json.dumps(existing,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    constraints=root/'requirements/recovery-tested.txt'
    constraints.parent.mkdir(exist_ok=True)
    constraints.write_text('# Tested runtime versions (Windows Python 3.13); cross-platform CI constraints.\n'+
                           '\n'.join(name+'=='+info['version'] for name,info in sorted(seen.items()))+'\n',encoding='utf-8')
    print('Recorded',len(seen),'runtime packages and',len(sources),'source checkouts')


if __name__=='__main__':
    main()
