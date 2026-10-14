"""Call-linked conservative repair planning. Alerts alone do not prove guilt."""
from .store import ProvenanceStore


class RepairPlanner:
    def __init__(self, store: ProvenanceStore):
        self.store = store

    def candidates(self, call_id: str) -> set[str]:
        call = self.store.call(call_id)
        seen: set[str] = set()
        todo = [node_id for node_id, _ in call["bindings"]]
        while todo:
            node_id = todo.pop()
            self.store.get(node_id)
            if node_id in seen:
                continue
            seen.add(node_id)
            todo.extend(row[0] for row in self.store.db.execute(
                "SELECT parent FROM edges WHERE child=?", (node_id,)))
        return seen

    def apply(self, call_id: str, confirmed_roots: tuple[str, ...], evidence: str) -> list[str]:
        if not evidence.strip():
            raise ValueError("Record localization evidence before applying a repair")
        candidates = self.candidates(call_id)
        if not confirmed_roots or not set(confirmed_roots).issubset(candidates):
            raise ValueError("Confirmed roots must be in the call's captured ancestry")
        return self.store.quarantine(confirmed_roots, f"call={call_id}; {evidence}")
