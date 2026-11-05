"""Build a complete typed provenance graph from trusted host records."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .model import (
    DependencyGraph, EdgeType, GraphNode, NodeKind, ProvenanceError,
)


PRODUCING_STEPS = frozenset({
    'memory_write', 'memory_update', 'memory_consolidate',
})
CONSUMING_STEPS = {
    'memory_delete': EdgeType.DELETE.value,
    'memory_update': EdgeType.UPDATE.value,
    'memory_consolidate': EdgeType.CONSOLIDATE.value,
}


def is_memory_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith('m_')


def is_step_id(value: Any) -> bool:
    return isinstance(value, str) and value.startswith('s_')


def user_input_id(turn: int) -> str:
    return f'user_input_{turn}'


def _id_list(record: dict[str, Any], field: str) -> tuple[str, ...]:
    value = record.get(field, ())
    if not isinstance(value, (list, tuple)) or any(not isinstance(x, str) for x in value):
        raise ProvenanceError('invalid_' + field)
    if len(set(value)) != len(value):
        raise ProvenanceError('duplicate_' + field)
    return tuple(value)


def _assign_turns(steps: tuple[dict[str, Any], ...]) -> dict[str, int]:
    turns = {}
    current = 0
    for step in steps:
        step_id = step.get('step_id')
        if not is_step_id(step_id):
            raise ProvenanceError('invalid_step_id')
        if step.get('step_type') == 'memory_read':
            current += 1
        turns[step_id] = max(current, 1)
    return turns


def build_dependency_graph(
    task_id: str,
    steps: Iterable[dict[str, Any]],
    memories: Iterable[dict[str, Any]],
    session: Iterable[str],
) -> DependencyGraph:
    """Build all node and edge types without making a fault judgment."""
    steps = tuple(steps)
    memories = tuple(memories)
    session = tuple(session)
    if any(not isinstance(item, dict) for item in (*steps, *memories)):
        raise ProvenanceError('invalid_records')
    if any(not isinstance(text, str) for text in session):
        raise ProvenanceError('invalid_session')

    step_turn = _assign_turns(steps)
    n_turns = max(step_turn.values(), default=0)
    nodes: dict[str, GraphNode] = {}

    def add_node(node: GraphNode):
        if node.node_id in nodes:
            raise ProvenanceError('duplicate_node')
        nodes[node.node_id] = node

    for turn, text in enumerate(session, 1):
        add_node(GraphNode(
            user_input_id(turn), NodeKind.USER_INPUT, turn=turn,
            raw={'turn': turn, 'text': text},
        ))
    for step in steps:
        step_id = step['step_id']
        add_node(GraphNode(
            step_id, NodeKind.STEP, step_type=step.get('step_type'),
            turn=step_turn[step_id], raw=dict(step),
        ))
    for memory in memories:
        memory_id = memory.get('memory_id')
        if not is_memory_id(memory_id):
            raise ProvenanceError('invalid_memory_id')
        add_node(GraphNode(
            memory_id, NodeKind.MEMORY,
            memory_status=memory.get('status'), raw=dict(memory),
        ))

    edges: dict[str, dict[str, set[str]]] = {}
    missing: set[str] = set()

    def connect(source: str, target: str, kind: EdgeType):
        if source not in nodes or target not in nodes:
            missing.add(f'{source}->{target}:{kind.value}')
            return
        edges.setdefault(source, {}).setdefault(target, set()).add(kind.value)

    # 1. Execution order.
    for step in steps:
        for target in _id_list(step, 'next_step_ids'):
            if not is_step_id(target):
                raise ProvenanceError('invalid_chain_target')
            connect(step['step_id'], target, EdgeType.CHAIN)

    # 2. Writer outputs.
    for step in steps:
        if step.get('step_type') in PRODUCING_STEPS:
            for memory_id in _id_list(step, 'generated_memory_ids'):
                if not is_memory_id(memory_id):
                    raise ProvenanceError('invalid_generated_memory')
                connect(step['step_id'], memory_id, EdgeType.PRODUCE)

    # 3. Memory evidence and non-memory citations.
    for step in steps:
        for used_id in _id_list(step, 'used_ids'):
            if is_memory_id(used_id):
                connect(used_id, step['step_id'], EdgeType.SUPPORT)
            else:
                connect(used_id, step['step_id'], EdgeType.CITE)

    # 4. Memory mutation inputs.
    for step in steps:
        label = CONSUMING_STEPS.get(step.get('step_type'))
        if label is not None:
            for memory_id in _id_list(step, 'invalidated_memory_ids'):
                if not is_memory_id(memory_id):
                    raise ProvenanceError('invalid_invalidated_memory')
                connect(memory_id, step['step_id'], EdgeType(label))

    # 5. User turn anchors.
    first_by_turn: dict[int, str] = {}
    for step in steps:
        first_by_turn.setdefault(step_turn[step['step_id']], step['step_id'])
    for turn in range(1, n_turns + 1):
        target = first_by_turn.get(turn)
        if target is not None:
            connect(user_input_id(turn), target, EdgeType.INITIATE)

    # 6. Memory lineage and replacement.
    for memory in memories:
        memory_id = memory['memory_id']
        for ancestor in _id_list(memory, 'derived_from'):
            if not is_memory_id(ancestor):
                raise ProvenanceError('invalid_derived_from')
            connect(ancestor, memory_id, EdgeType.DERIVE)
        supersedes = memory.get('supersedes')
        if supersedes is not None:
            if not is_memory_id(supersedes):
                raise ProvenanceError('invalid_supersedes')
            connect(supersedes, memory_id, EdgeType.SUPERSEDE)

    return DependencyGraph(
        task_id,
        nodes,
        edges,
        step_turn=step_turn,
        n_turns=n_turns,
        coverage='partial' if missing else 'complete_within_scope',
        missing_refs=missing,
    )
