"""Dependency-guided affected-subgraph reachability for Ariadne.

This is an independent implementation of the graph method described in
"From Faulty Memories to Corrected Actions" (arXiv:2608.10502). It follows
the paper's typed dependency graph and multi-seed downstream-closure design,
but uses Ariadne's contracts so the team can modify it here. No source from
the authors' repository is copied into this module.
"""
from cua_guard.provenance.model import (
    DependencyGraph as ProvenanceGraph,
    EdgeType,
    GraphNode,
    NodeKind,
    ProvenanceError,
)
from cua_guard.provenance.query import affected_node_ids as provenance_affected

from .contracts import RecoveryError, identity


class DependencyGraph:
    """Compatibility view over the complete provenance graph engine."""

    def __init__(self, node_ids, edges, *, reverse=False):
        self.nodes = frozenset(node_ids)
        if not self.nodes:
            raise RecoveryError('empty_graph')
        for node_id in self.nodes:
            identity(node_id)

        adjacency = {}
        normalized = {}
        for edge in edges:
            source, target = (
                (edge.target, edge.source) if reverse
                else (edge.source, edge.target)
            )
            if source not in self.nodes or target not in self.nodes:
                raise RecoveryError('missing_edge_endpoint')
            adjacency.setdefault(source, {}).setdefault(target, set()).add(edge.kind)
            normalized.setdefault(source, {}).setdefault(target, set()).add(
                EdgeType.DERIVE.value
            )
        self._edge_kinds = {
            source: {
                target: frozenset(labels)
                for target, labels in destinations.items()
            }
            for source, destinations in adjacency.items()
        }
        try:
            self._graph = ProvenanceGraph(
                'recovery-compatibility',
                {
                    node_id: GraphNode(node_id, NodeKind.MEMORY)
                    for node_id in self.nodes
                },
                normalized,
            )
        except ProvenanceError as exc:
            raise RecoveryError(exc.code) from exc

    def successors(self, node_id):
        if node_id not in self.nodes:
            raise RecoveryError('unknown_root')
        return self._graph.successors(node_id)

    def edge_kinds(self, source, target):
        return self._edge_kinds.get(source, {}).get(target, frozenset())

    def descendants(self, roots):
        try:
            return provenance_affected(self._graph, *roots)
        except ProvenanceError as exc:
            raise RecoveryError(exc.code) from exc


def affected_node_ids(graph, *roots):
    """Return every direct or transitive dependant of one or more roots."""
    return graph.descendants(roots)


class DGRRReachability:
    """Adapter exposing the local DGRR-style graph through Ariadne's protocol."""

    identity = 'ariadne-dgrr-reimplementation/1@arxiv:2608.10502'

    def closure(self, node_ids, edges, roots, *, reverse=False):
        roots = tuple(roots)
        graph = DependencyGraph(node_ids, edges, reverse=reverse)
        return set(roots) | set(affected_node_ids(graph, *roots))
