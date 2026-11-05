"""Deterministic JSON and standalone SVG export."""
from __future__ import annotations

from html import escape
import json
from pathlib import Path

from .model import DependencyGraph, NodeKind, ProvenanceError
from .validate import validate_graph


MAX_JSON_BYTES = 32_000_000


def write_json(graph: DependencyGraph, path) -> Path:
    validate_graph(graph).raise_for_errors()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(
        graph.to_dict(), ensure_ascii=False, sort_keys=True, indent=2,
        allow_nan=False,
    ) + '\n'
    if len(text.encode('utf-8')) > MAX_JSON_BYTES:
        raise ProvenanceError('graph_budget_exceeded')
    path.write_text(text, encoding='utf-8')
    return path


def read_json(path) -> DependencyGraph:
    path = Path(path)
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ProvenanceError('graph_budget_exceeded')
    try:
        graph = DependencyGraph.from_dict(
            json.loads(path.read_text(encoding='utf-8'))
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise ProvenanceError('invalid_graph_payload') from exc
    validate_graph(graph).raise_for_errors()
    return graph


def to_svg(
    graph: DependencyGraph, *, roots=(), affected=(),
) -> str:
    """Render a stable, dependency-free SVG suitable for reports."""
    validate_graph(graph).raise_for_errors()
    roots, affected = set(roots), set(affected)
    if not roots | affected <= graph.nodes.keys():
        raise ProvenanceError('unknown_node')

    lanes = {
        NodeKind.USER_INPUT: 140,
        NodeKind.STEP: 560,
        NodeKind.MEMORY: 980,
    }
    counters = {kind: 0 for kind in lanes}
    positions = {}
    for node_id in sorted(
        graph.nodes,
        key=lambda key: (
            list(NodeKind).index(graph.nodes[key].node_kind),
            graph.nodes[key].turn or 0,
            key,
        ),
    ):
        kind = graph.nodes[node_id].node_kind
        positions[node_id] = (lanes[kind], 100 + counters[kind] * 90)
        counters[kind] += 1
    height = max(260, max((y for _, y in positions.values()), default=100) + 100)
    width = 1120

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'role="img" aria-label="Provenance graph {escape(graph.task_id)}">',
        '<defs><marker id="arrow" markerWidth="8" markerHeight="8" '
        'refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" '
        'fill="#64748b"/></marker></defs>',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#0f172a}'
        '.edge{stroke:#64748b;stroke-width:1.4;marker-end:url(#arrow)}'
        '.node{stroke:#334155;stroke-width:1.5}'
        '.root{stroke:#b91c1c;stroke-width:3}'
        '.affected{stroke:#c2410c;stroke-width:3}'
        '.label{font-size:12px;text-anchor:middle}'
        '.edgeLabel{font-size:10px;text-anchor:middle;fill:#475569}'
        '.lane{font-size:14px;font-weight:bold;text-anchor:middle}</style>',
    ]
    for kind, x in lanes.items():
        parts.append(
            f'<text class="lane" x="{x}" y="28">{escape(kind.value)}</text>'
        )

    for source in sorted(graph.forward_edges):
        x1, y1 = positions[source]
        for target, labels in sorted(graph.forward_edges[source].items()):
            x2, y2 = positions[target]
            parts.append(
                f'<line class="edge" x1="{x1}" y1="{y1}" '
                f'x2="{x2}" y2="{y2}"/>'
            )
            parts.append(
                f'<text class="edgeLabel" x="{(x1 + x2) / 2:.1f}" '
                f'y="{(y1 + y2) / 2 - 4:.1f}">'
                f'{escape(",".join(sorted(labels)))}</text>'
            )

    fills = {
        NodeKind.USER_INPUT: '#dbeafe',
        NodeKind.STEP: '#e2e8f0',
        NodeKind.MEMORY: '#dcfce7',
    }
    for node_id in sorted(positions):
        node = graph.nodes[node_id]
        x, y = positions[node_id]
        css = 'node'
        if node_id in roots:
            css += ' root'
        elif node_id in affected:
            css += ' affected'
        parts.extend([
            f'<rect class="{css}" x="{x - 82}" y="{y - 24}" '
            f'width="164" height="48" rx="6" fill="{fills[node.node_kind]}"/>',
            f'<text class="label" x="{x}" y="{y - 3}">'
            f'{escape(node_id)}</text>',
            f'<text class="label" x="{x}" y="{y + 14}">'
            f'{escape(node.semantic_type)}</text>',
        ])
    parts.append('</svg>')
    return ''.join(parts)


def write_svg(
    graph: DependencyGraph, path, *, roots=(), affected=(),
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        to_svg(graph, roots=roots, affected=affected), encoding='utf-8',
    )
    return path
