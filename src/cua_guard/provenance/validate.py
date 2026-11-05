"""Structural validation for complete provenance graphs."""
from __future__ import annotations

from dataclasses import dataclass

from .builder import PRODUCING_STEPS, user_input_id
from .model import DependencyGraph, EdgeType, NodeKind, ProvenanceError
from .query import topological_order


@dataclass(frozen=True)
class ValidationReport:
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors

    def raise_for_errors(self):
        if self.errors:
            raise ProvenanceError(self.errors[0])


def validate_graph(graph: DependencyGraph) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []

    if graph.coverage != 'complete_within_scope' or graph.missing_refs:
        errors.append('incomplete_graph')

    known_labels = {edge.value for edge in EdgeType}
    for source, destinations in graph.forward_edges.items():
        if source not in graph.nodes:
            errors.append('missing_edge_endpoint')
        for target, labels in destinations.items():
            if target not in graph.nodes:
                errors.append('missing_edge_endpoint')
                continue
            if not labels or not labels <= known_labels:
                errors.append('unsupported_edge')
            if graph.backward_edges.get(target, {}).get(source) != labels:
                errors.append('asymmetric_edge_index')
            if labels & {EdgeType.DERIVE.value, EdgeType.SUPERSEDE.value}:
                if (
                    graph.nodes[source].node_kind is not NodeKind.MEMORY
                    or graph.nodes[target].node_kind is not NodeKind.MEMORY
                ):
                    errors.append('invalid_memory_lineage_edge')
    for target, sources in graph.backward_edges.items():
        for source, labels in sources.items():
            if graph.forward_edges.get(source, {}).get(target) != labels:
                errors.append('asymmetric_edge_index')

    step_turn = {
        node_id: node.turn for node_id, node in graph.nodes.items()
        if node.node_kind is NodeKind.STEP
    }
    if step_turn != graph.step_turn:
        errors.append('step_turn_mismatch')
    if max(step_turn.values(), default=0) != graph.n_turns:
        errors.append('turn_count_mismatch')

    for node_id, node in graph.nodes.items():
        incoming = graph.predecessor_edges(node_id)
        outgoing = graph.successor_edges(node_id)
        if node.node_kind is NodeKind.MEMORY:
            if not incoming and not outgoing:
                warnings.append('isolated_memory:' + node_id)
            for ancestor in node.raw.get('derived_from', ()):
                if EdgeType.DERIVE.value not in graph.edge_types(ancestor, node_id):
                    errors.append('missing_derive_edge')
            supersedes = node.raw.get('supersedes')
            if supersedes and EdgeType.SUPERSEDE.value not in graph.edge_types(
                supersedes, node_id
            ):
                errors.append('missing_supersede_edge')
        elif node.node_kind is NodeKind.STEP and node.step_type in PRODUCING_STEPS:
            produced = graph.successors(
                node_id, include={EdgeType.PRODUCE.value},
            )
            if not produced:
                warnings.append('writer_without_output:' + node_id)
        elif node.node_kind is NodeKind.USER_INPUT:
            initiated = [
                target for target, labels in outgoing.items()
                if EdgeType.INITIATE.value in labels
            ]
            if node.turn <= graph.n_turns and len(initiated) != 1:
                errors.append('invalid_initiate_edge')

    for turn in range(1, graph.n_turns + 1):
        if user_input_id(turn) not in graph.nodes:
            errors.append('missing_user_input')

    try:
        topological_order(graph)
    except ProvenanceError as exc:
        errors.append(exc.code)

    return ValidationReport(
        tuple(dict.fromkeys(errors)),
        tuple(dict.fromkeys(warnings)),
    )
