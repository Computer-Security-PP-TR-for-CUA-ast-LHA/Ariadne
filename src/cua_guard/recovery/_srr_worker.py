"""Read-only native plan adapter. Original source is NOT redistributed."""
import json
from pathlib import Path
import subprocess
import sys

PIN = 'd7bcb32740156cb985fae0ee93caba35ee45e67e'


def main():
    root = Path(sys.argv[1]).resolve()
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True,
                              encoding='utf-8', timeout=10).stdout.strip()
    if git('rev-parse', 'HEAD') != PIN or git('status', '--porcelain', '--untracked-files=all', '--', 'src'):
        raise ValueError('unqualified checkout')
    data = json.loads(sys.stdin.buffer.read(1_000_001))
    run_dir = Path(data['run_dir'])
    for name in ('objects.jsonl', 'events.jsonl'):
        path = run_dir / name
        if not path.is_file() or path.stat().st_size > 16_000_000:
            raise ValueError('invalid native history')
    if not (run_dir / 'checkpoints').is_dir():
        raise ValueError('missing checkpoints directory')
    sys.path.insert(0, str(root))
    from src.store import RunRegistry
    from src.recover import compute_persisted_descendant_closure, build_replay_plan
    registry = RunRegistry(run_dir)
    if any(n not in registry.objects for n in data['roots']):
        raise ValueError('unknown root')
    if any(p not in registry.objects for v in registry.objects.values() for p in v.parent_ids):
        raise ValueError('incomplete graph')
    closure = compute_persisted_descendant_closure(registry, data['roots'])
    plan = build_replay_plan(registry, 'ariadne-input', 'ariadne-candidate', data['roots'], closure)
    sys.stdout.write(json.dumps(plan.to_dict(), ensure_ascii=True))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        sys.stderr.write('native SRR planner failed\n')
        sys.exit(1)
