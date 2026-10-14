"""Deterministic mechanism demo. No model, exploit or real transmission."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .gate import Action, Capability, ExecutionGate
from .repair import RepairPlanner
from .store import ProvenanceStore


def run(path: Path) -> dict:
    store = ProvenanceStore(path)
    try:
        good = store.ingest("user-plan", "Prepare the approved project summary.", "user")
        source = store.ingest("external-page", "Synthetic contaminated observation.")
        note = store.derive("notes", "Synthetic mixed summary.", (good, source))
        copied = store.derive("copied-file", "Synthetic downstream copy.", (note,))
        stable = store.derive("unrelated-note", "Keep the project meeting date.", (good,))
        store.close()
        store = ProvenanceStore(path)  # New session, durable lineage.
        gate = ExecutionGate(store)
        cap = Capability("task-B", "publish", "approved-report", "local-approved-sink")
        attack = Action("call-alert", "task-B", "publish", "private-fixture", "local-test-sink",
                        ((copied, store.get(copied)["hash"]),))
        delivered: list[str] = []
        try:
            gate.dispatch(attack, (cap,), lambda a: delivered.append(a.resource))
        except PermissionError:
            pass
        affected = RepairPlanner(store).apply("call-alert", (source,), "synthetic oracle root")
        replacement = store.rebuild(note, "Approved project summary.", (good,))
        action = Action("call-recovered", "task-B", "publish", "approved-report",
                        "local-approved-sink", ((replacement, store.get(replacement)["hash"]),))
        gate.dispatch(action, (cap,), lambda a: delivered.append(a.resource))
        return {"kind": "deterministic_mechanism_demo", "model_calls": 0,
                "unauthorized_delivered": "private-fixture" in delivered,
                "quarantined_versions": len(affected),
                "unrelated_state_preserved": store.get(stable)["status"] == "active",
                "old_copy_retrievable": store.verify(store.envelope(copied), store.get(copied)["content"]),
                "recovered_local_action": "approved-report" in delivered,
                "limitation": "Oracle root and host-provided clean rebuild; no CUA/LLM evaluation."}
    finally:
        store.close()


def main() -> None:
    with TemporaryDirectory() as temp:
        print(json.dumps(run(Path(temp) / "demo.sqlite"), indent=2))


if __name__ == "__main__":
    main()
