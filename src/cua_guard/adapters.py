"""Required contracts for future framework adapters; not live integrations."""
from typing import Protocol

from .gate import Action


class HostAdapter(Protocol):
    def capture_input_ids(self) -> tuple[str, ...]:
        """Capture all model-visible inputs outside model control."""
        ...

    def execute_bound(self, action: Action) -> object:
        """Execute exact authorized bytes/resource/recipient, without bypasses."""
        ...

    def rebuild_context(self, active_ids: tuple[str, ...]) -> None:
        """Reset live context, caches and retrieval to active versions only."""
        ...

    def checkpoint(self) -> str:
        """Capture environment + memory + task state for controlled replay."""
        ...
