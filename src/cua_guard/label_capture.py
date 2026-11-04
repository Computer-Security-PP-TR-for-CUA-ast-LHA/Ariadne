"""Host-side capture contract for AgentLAB Email and RedTeamCUA observations.

Adapters accept outputs from a trusted benchmark harness. Text contained in an
email, screenshot or tool result is never allowed to declare its own label.
"""
from __future__ import annotations

import hashlib
import json

from .label_store import Confidentiality, PersistentLabelStore


def capture_agentlab_task(store: PersistentLabelStore, task_id: str, task: str) -> str:
    return store.ingest(f"agentlab:task:{task_id}", task, "user")


def capture_agentlab_email(store: PersistentLabelStore, task_id: str,
                           message: dict, *, principal: str) -> str:
    """Called after the harness reads an Email environment tool response."""
    if not task_id or not principal:
        raise ValueError("Task and authenticated principal required")
    if not isinstance(message, dict):
        raise TypeError("Email tool result must be an object")
    content = json.dumps(message, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return store.ingest(f"agentlab:email:{task_id}", content, "tool",
                        Confidentiality.USER_IDENTITY, frozenset({principal}))


def capture_redteam_task(store: PersistentLabelStore, case_id: str,
                         instruction: str) -> str:
    return store.ingest(f"redteam:task:{case_id}", instruction, "user")


def capture_redteam_observation(store: PersistentLabelStore, case_id: str,
                                screenshot: bytes, accessibility_tree: str) -> str:
    """Bind screenshot bytes to the text observation for later version checks."""
    if not isinstance(screenshot, bytes) or not screenshot:
        raise ValueError("Nonempty screenshot bytes required")
    if not isinstance(accessibility_tree, str):
        raise TypeError("Accessibility tree must be text")
    observation = json.dumps({"image_sha256": hashlib.sha256(screenshot).hexdigest(),
                              "accessibility_tree": accessibility_tree},
                             sort_keys=True, ensure_ascii=False)
    return store.ingest(f"redteam:screen:{case_id}", observation, "external")


def capture_summary(store: PersistentLabelStore, task_id: str, summary: str,
                    actual_input_ids: tuple[str, ...]) -> str:
    """The harness supplies every captured input read by the summarizer."""
    return store.derive(f"memory:summary:{task_id}", summary, actual_input_ids)
