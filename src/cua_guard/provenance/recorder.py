"""Host-facing recorder for incrementally captured provenance records."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from .builder import build_dependency_graph
from .model import DependencyGraph, ProvenanceError


class ProvenanceRecorder:
    """Collect explicit host observations; never infer dependencies from text."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self._session: list[str] = []
        self._steps: list[dict[str, Any]] = []
        self._memories: list[dict[str, Any]] = []
        self._sealed = False

    def _check_open(self):
        if self._sealed:
            raise ProvenanceError('recorder_sealed')

    def record_user_input(self, text: str):
        self._check_open()
        if not isinstance(text, str):
            raise ProvenanceError('invalid_session')
        self._session.append(text)

    def record_step(
        self, step_id: str, step_type: str, *,
        next_step_ids=(), used_ids=(), generated_memory_ids=(),
        invalidated_memory_ids=(), **metadata,
    ):
        self._check_open()
        self._steps.append({
            **deepcopy(metadata),
            'step_id': step_id,
            'step_type': step_type,
            'next_step_ids': list(next_step_ids),
            'used_ids': list(used_ids),
            'generated_memory_ids': list(generated_memory_ids),
            'invalidated_memory_ids': list(invalidated_memory_ids),
        })

    def record_memory(
        self, memory_id: str, *, status: str = 'active',
        derived_from=(), supersedes=None, **metadata,
    ):
        self._check_open()
        self._memories.append({
            **deepcopy(metadata),
            'memory_id': memory_id,
            'status': status,
            'derived_from': list(derived_from),
            'supersedes': supersedes,
        })

    def build(self, *, seal: bool = True) -> DependencyGraph:
        graph = build_dependency_graph(
            self.task_id,
            deepcopy(self._steps),
            deepcopy(self._memories),
            tuple(self._session),
        )
        if seal:
            self._sealed = True
        return graph
