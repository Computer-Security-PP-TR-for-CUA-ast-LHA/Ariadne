"""Typed provenance graph contracts.

The model is an independent implementation of the graph concepts described in
arXiv:2608.10502. It deliberately contains no repair or rollback policy.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


SCHEMA = 'ariadne.provenance/1.0'


class ProvenanceError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class NodeKind(str, Enum):
    USER_INPUT = 'user_input'
    STEP = 'step'
    MEMORY = 'memory'


class EdgeType(str, Enum):
    CHAIN = 'chain'
    PRODUCE = 'produce'
    SUPPORT = 'support'
    DELETE = 'delete'
    UPDATE = 'update'
    CONSOLIDATE = 'consolidate'
    INITIATE = 'initiate'
    DERIVE = 'derive'
    SUPERSEDE = 'supersede'
    CITE = 'cite'


STEP_TYPES = frozenset({
    'memory_read', 'claim', 'plan', 'tool_action', 'tool_observation',
    'final_answer', 'memory_write', 'memory_update', 'memory_delete',
    'memory_consolidate',
})


def _identity(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 512:
        raise ProvenanceError('invalid_identity')
    return value


@dataclass(frozen=True)
class GraphNode:
    node_id: str
    node_kind: NodeKind
    step_type: str | None = None
    turn: int | None = None
    memory_status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        _identity(self.node_id)
        if not isinstance(self.node_kind, NodeKind):
            raise ProvenanceError('invalid_node_kind')
        if self.node_kind is NodeKind.STEP:
            if self.step_type not in STEP_TYPES:
                raise ProvenanceError('invalid_step_type')
            if type(self.turn) is not int or self.turn < 1:
                raise ProvenanceError('invalid_turn')
            if self.memory_status is not None:
                raise ProvenanceError('invalid_step_node')
        elif self.node_kind is NodeKind.USER_INPUT:
            if type(self.turn) is not int or self.turn < 1:
                raise ProvenanceError('invalid_turn')
            if self.step_type is not None or self.memory_status is not None:
                raise ProvenanceError('invalid_user_input_node')
        elif self.step_type is not None or self.turn is not None:
            raise ProvenanceError('invalid_memory_node')
        if not isinstance(self.raw, dict):
            raise ProvenanceError('invalid_raw_record')

    @property
    def semantic_type(self) -> str:
        return self.step_type if self.node_kind is NodeKind.STEP else self.node_kind.value

    def to_dict(self) -> dict[str, Any]:
        return {
            'node_id': self.node_id,
            'node_kind': self.node_kind.value,
            'semantic_type': self.semantic_type,
            'step_type': self.step_type,
            'turn': self.turn,
            'memory_status': self.memory_status,
            'raw': self.raw,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> GraphNode:
        if not isinstance(value, dict):
            raise ProvenanceError('invalid_node_payload')
        allowed = {
            'node_id', 'node_kind', 'semantic_type', 'step_type', 'turn',
            'memory_status', 'raw',
        }
        if set(value) - allowed:
            raise ProvenanceError('unsupported_node_fields')
        try:
            return cls(
                node_id=value['node_id'],
                node_kind=NodeKind(value['node_kind']),
                step_type=value.get('step_type'),
                turn=value.get('turn'),
                memory_status=value.get('memory_status'),
                raw=value.get('raw', {}),
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, ProvenanceError):
                raise
            raise ProvenanceError('invalid_node_payload') from exc


class DependencyGraph:
    """Directed graph whose node pairs may carry multiple edge labels."""

    def __init__(
        self,
        task_id: str,
        nodes: dict[str, GraphNode],
        forward_edges: dict[str, dict[str, Iterable[str]]] | None = None,
        *,
        step_turn: dict[str, int] | None = None,
        n_turns: int = 0,
        coverage: str = 'complete_within_scope',
        missing_refs: Iterable[str] = (),
    ):
        self.task_id = _identity(task_id)
        if not isinstance(nodes, dict) or any(key != node.node_id for key, node in nodes.items()):
            raise ProvenanceError('invalid_nodes')
        self.nodes = dict(nodes)
        self.forward_edges: dict[str, dict[str, frozenset[str]]] = {}
        self.backward_edges: dict[str, dict[str, frozenset[str]]] = {}
        for source, destinations in (forward_edges or {}).items():
            for target, labels in destinations.items():
                self._store_edge(source, target, labels)
        self.step_turn = dict(step_turn or {})
        if type(n_turns) is not int or n_turns < 0:
            raise ProvenanceError('invalid_turn_count')
        self.n_turns = n_turns
        if coverage not in {'complete_within_scope', 'partial'}:
            raise ProvenanceError('invalid_coverage')
        self.coverage = coverage
        self.missing_refs = tuple(sorted(set(missing_refs)))
        for ref in self.missing_refs:
            _identity(ref)

    def _store_edge(self, source: str, target: str, labels: Iterable[str]):
        if source not in self.nodes or target not in self.nodes:
            raise ProvenanceError('missing_edge_endpoint')
        try:
            normalized = frozenset(EdgeType(label).value for label in labels)
        except (TypeError, ValueError) as exc:
            raise ProvenanceError('unsupported_edge') from exc
        if not normalized:
            raise ProvenanceError('empty_edge_labels')
        old = self.forward_edges.get(source, {}).get(target, frozenset())
        merged = old | normalized
        self.forward_edges.setdefault(source, {})[target] = merged
        self.backward_edges.setdefault(target, {})[source] = merged

    def node(self, node_id: str) -> GraphNode | None:
        return self.nodes.get(node_id)

    def edge_types(self, source: str, target: str) -> frozenset[str]:
        return self.forward_edges.get(source, {}).get(target, frozenset())

    def successor_edges(self, node_id: str) -> dict[str, frozenset[str]]:
        return dict(self.forward_edges.get(node_id, {}))

    def predecessor_edges(self, node_id: str) -> dict[str, frozenset[str]]:
        return dict(self.backward_edges.get(node_id, {}))

    def successors(
        self, node_id: str, *, include: Iterable[str] | None = None,
        exclude: Iterable[str] = (),
    ) -> frozenset[str]:
        if node_id not in self.nodes:
            raise ProvenanceError('unknown_node')
        included = None if include is None else frozenset(include)
        excluded = frozenset(exclude)
        return frozenset(
            target for target, labels in self.forward_edges.get(node_id, {}).items()
            if (labels if included is None else labels & included) - excluded
        )

    def predecessors(
        self, node_id: str, *, include: Iterable[str] | None = None,
        exclude: Iterable[str] = (),
    ) -> frozenset[str]:
        if node_id not in self.nodes:
            raise ProvenanceError('unknown_node')
        included = None if include is None else frozenset(include)
        excluded = frozenset(exclude)
        return frozenset(
            source for source, labels in self.backward_edges.get(node_id, {}).items()
            if (labels if included is None else labels & included) - excluded
        )

    def walk(
        self, roots: Iterable[str], *, reverse: bool = False,
        include: Iterable[str] | None = None, exclude: Iterable[str] = (),
        include_roots: bool = False,
    ) -> tuple[str, ...]:
        roots = tuple(dict.fromkeys(roots))
        if not roots or any(root not in self.nodes for root in roots):
            raise ProvenanceError('unknown_root')
        seen = set(roots)
        result = list(sorted(roots)) if include_roots else []
        queue = deque(sorted(roots))
        while queue:
            current = queue.popleft()
            neighbours = (
                self.predecessors(current, include=include, exclude=exclude)
                if reverse else
                self.successors(current, include=include, exclude=exclude)
            )
            for neighbour in sorted(neighbours):
                if neighbour not in seen:
                    seen.add(neighbour)
                    result.append(neighbour)
                    queue.append(neighbour)
        return tuple(result)

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': SCHEMA,
            'task_id': self.task_id,
            'coverage': self.coverage,
            'missing_refs': list(self.missing_refs),
            'n_turns': self.n_turns,
            'step_turn': dict(sorted(self.step_turn.items())),
            'nodes': {
                key: self.nodes[key].to_dict() for key in sorted(self.nodes)
            },
            'forward_edges': {
                source: {
                    target: sorted(destinations[target])
                    for target in sorted(destinations)
                }
                for source, destinations in sorted(self.forward_edges.items())
            },
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> DependencyGraph:
        if not isinstance(value, dict) or value.get('schema_version') != SCHEMA:
            raise ProvenanceError('unsupported_schema')
        allowed = {
            'schema_version', 'task_id', 'coverage', 'missing_refs', 'n_turns',
            'step_turn', 'nodes', 'forward_edges',
        }
        if set(value) - allowed:
            raise ProvenanceError('unsupported_graph_fields')
        try:
            nodes = {
                key: GraphNode.from_dict(node)
                for key, node in value['nodes'].items()
            }
            return cls(
                value['task_id'],
                nodes,
                value.get('forward_edges', {}),
                step_turn=value.get('step_turn', {}),
                n_turns=value.get('n_turns', 0),
                coverage=value.get('coverage', 'partial'),
                missing_refs=value.get('missing_refs', ()),
            )
        except (KeyError, TypeError, AttributeError) as exc:
            raise ProvenanceError('invalid_graph_payload') from exc
