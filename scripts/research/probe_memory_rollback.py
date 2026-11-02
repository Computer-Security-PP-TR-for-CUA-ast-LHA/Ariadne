"""Read-only offline probes against a pinned author checkout; no vendored code."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys

COMMIT = '713724491b9bbc6e55f0f9d8723da0eb0766ced7'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--upstream', required=True, type=Path)
    args = parser.parse_args()
    root = args.upstream.resolve()
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != COMMIT:
        raise SystemExit(f'Expected {COMMIT}; observed {commit}')
    # Also check tracked files: the commit alone does not identify dirty code.
    if subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise SystemExit('Upstream has tracked modifications')
    sys.path.insert(0, str(root))
    from methods.ours.graph_schema import DependencyGraph, GraphNode
    from methods.ours.affected_subgraph import affected_node_ids
    from methods.ours.support_checker import has_trusted_support

    nodes = {n: GraphNode(n, 'memory' if n.startswith('m_') else 'step',
                         step_type=None if n.startswith('m_') else 'claim')
             for n in ('m_root', 'm_copy', 's_claim', 's_later', 's_unbacked')}
    forward = {'m_root': {'m_copy': {'derive'}},
               'm_copy': {'s_claim': {'support'}},
               's_claim': {'s_later': {'chain'}}}
    backward = {}
    for source, targets in forward.items():
        for target, labels in targets.items():
            backward.setdefault(target, {})[source] = set(labels)
    graph = DependencyGraph('synthetic', nodes, forward, backward, {}, 1)
    reached = affected_node_ids(graph, 'm_root')
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        missing = affected_node_ids(graph, 'm_missing')
    observations = {
        'derived_copy_and_consumer_reached': set(reached) == {'m_copy', 's_claim'},
        'pure_chain_edge_excluded': 's_later' not in reached,
        'missing_root_returns_empty_not_exception': missing == [],
        'unsupported_claim_preserved_by_upstream_default': has_trusted_support(graph, 's_unbacked', {'m_root'}),
    }
    print(json.dumps({'commit': commit, 'model_calls': 0, 'observations': observations,
                      'note': 'Last two checks characterize upstream behavior; they are not Ariadne safety acceptance criteria.'}, indent=2))
    if not all(observations.values()):
        raise SystemExit('Observed behavior differs from the reviewed contract')


if __name__ == '__main__':
    main()
