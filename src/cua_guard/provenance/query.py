"""Read-only provenance graph queries."""
from __future__ import annotations

from graphlib import CycleError, TopologicalSorter
from typing import Iterable

from .model import DependencyGraph, EdgeType, NodeKind, ProvenanceError


def descendants(
    graph: DependencyGraph, roots: Iterable[str], *,
    edge_types: Iterable[str] | None = None,
) -> tuple[str, ...]:
    return graph.walk(roots, include=edge_types)


def ancestors(
    graph: DependencyGraph, roots: Iterable[str], *,
    edge_types: Iterable[str] | None = None,
) -> tuple[str, ...]:
    return graph.walk(roots, reverse=True, include=edge_types)


def affected_node_ids(
    graph: DependencyGraph, *roots: str, include_roots: bool = False,
) -> tuple[str, ...]:
    """Reach dependants through evidence/production edges, never pure sequence."""
    return graph.walk(
        roots, exclude={EdgeType.CHAIN.value}, include_roots=include_roots,
    )


def induced_subgraph(
    graph: DependencyGraph, node_ids: Iterable[str],
) -> DependencyGraph:
    kept = set(node_ids)
    if not kept <= graph.nodes.keys():
        raise ProvenanceError('unknown_node')
    nodes = {node_id: graph.nodes[node_id] for node_id in kept}
    edges = {
        source: {
            target: labels for target, labels in destinations.items()
            if target in kept
        }
        for source, destinations in graph.forward_edges.items()
        if source in kept
    }
    edges = {source: targets for source, targets in edges.items() if targets}
    turns = {
        node_id: turn for node_id, turn in graph.step_turn.items()
        if node_id in kept
    }
    return DependencyGraph(
        graph.task_id + '::subgraph',
        nodes,
        edges,
        step_turn=turns,
        n_turns=max(turns.values(), default=0),
        coverage=graph.coverage,
        missing_refs=graph.missing_refs,
    )


def affected_subgraph(
    graph: DependencyGraph, *roots: str,
) -> DependencyGraph:
    return induced_subgraph(
        graph, affected_node_ids(graph, *roots, include_roots=True),
    )


def find_producing_step(graph: DependencyGraph, memory_id: str) -> str | None:
    node = graph.node(memory_id)
    if node is None or node.node_kind is not NodeKind.MEMORY:
        raise ProvenanceError('unknown_memory')
    producers = sorted(graph.predecessors(
        memory_id, include={EdgeType.PRODUCE.value},
    ))
    if len(producers) > 1:
        raise ProvenanceError('multiple_memory_producers')
    return producers[0] if producers else None


def writers_for_versions(
    graph: DependencyGraph, memory_ids: Iterable[str],
) -> dict[str, str | None]:
    return {
        memory_id: find_producing_step(graph, memory_id)
        for memory_id in memory_ids
    }


def topological_order(
    graph: DependencyGraph, node_ids: Iterable[str] | None = None, *,
    edge_types: Iterable[str] | None = None,
) -> tuple[str, ...]:
    kept = set(graph.nodes if node_ids is None else node_ids)
    if not kept <= graph.nodes.keys():
        raise ProvenanceError('unknown_node')
    allowed = None if edge_types is None else set(edge_types)
    dependencies = {node_id: set() for node_id in kept}
    for source, destinations in graph.forward_edges.items():
        if source not in kept:
            continue
        for target, labels in destinations.items():
            if target in kept and (allowed is None or labels & allowed):
                dependencies[target].add(source)
    try:
        return tuple(TopologicalSorter({
            key: sorted(value) for key, value in sorted(dependencies.items())
        }).static_order())
    except CycleError as exc:
        raise ProvenanceError('cycle_detected') from exc


def affected_report(graph: DependencyGraph, *roots: str) -> dict:
    reached = affected_node_ids(graph, *roots)
    grouped: dict[str, list[str]] = {}
    for node_id in reached:
        grouped.setdefault(graph.nodes[node_id].semantic_type, []).append(node_id)
    return {
        'task_id': graph.task_id,
        'roots': list(roots),
        'affected_node_ids': list(reached),
        'nodes_by_type': {
            key: sorted(value) for key, value in sorted(grouped.items())
        },
        'counts_by_type': {
            key: len(value) for key, value in sorted(grouped.items())
        },
        'total_affected': len(reached),
    }
