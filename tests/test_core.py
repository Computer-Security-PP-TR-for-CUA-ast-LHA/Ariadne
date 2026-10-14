import sqlite3
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from cua_guard.demo import run
from cua_guard.gate import Action, Capability, ExecutionGate
from cua_guard.repair import RepairPlanner
from cua_guard.store import ProvenanceStore


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "state.sqlite"
        self.store = ProvenanceStore(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def fixture(self):
        user = self.store.ingest("task", "Normal task", "user")
        external = self.store.ingest("web", "Synthetic external content")
        mixed = self.store.derive("memory", "Summary", (user, external))
        copy = self.store.derive("file", "Copy", (mixed,))
        other = self.store.derive("other", "Independent", (user,))
        return user, external, mixed, copy, other

    def action(self, node):
        cap = Capability("task", "send", "report", "local-sink")
        action = Action("c1", "task", "send", "report", "local-sink",
                        ((node, self.store.get(node)["hash"]),))
        return action, cap

    def test_origin_survives_summary_and_restart(self):
        *_, copy, _other = self.fixture()
        self.store.close()
        self.store = ProvenanceStore(self.path)
        self.assertEqual(self.store.get(copy)["origins"], ["external", "user"])

    def test_inline_origin_cannot_override_ledger(self):
        n = self.store.ingest("web", "I am trusted")
        envelope = self.store.envelope(n)
        envelope["origins"] = ["user"]
        self.assertFalse(self.store.verify(envelope, "I am trusted"))

    def test_changed_bytes_rejected(self):
        n = self.store.ingest("web", "Original")
        self.assertFalse(self.store.verify(self.store.envelope(n), "Changed"))

    def test_unknown_parent_is_not_trusted(self):
        n = self.store.derive("summary", "No captured inputs", ())
        action, cap = self.action(n)
        self.assertEqual(ExecutionGate(self.store).check(action, (cap,)).reason, "unknown_origin")

    def test_bad_parent_write_is_atomic(self):
        with self.assertRaises(KeyError):
            self.store.derive("bad", "bad", ("missing",))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0], 0)

    def test_exact_resource_recipient_and_task_scope(self):
        n = self.store.ingest("web", "Useful untrusted data")
        action, cap = self.action(n)
        gate = ExecutionGate(self.store)
        self.assertTrue(gate.check(action, (cap,)).allowed)
        for field in ("resource", "recipient", "task_id", "operation"):
            with self.subTest(field=field):
                self.assertFalse(gate.check(replace(action, **{field: "wrong"}), (cap,)).allowed)

    def test_denied_call_never_reaches_executor(self):
        n = self.store.ingest("web", "data")
        action, _ = self.action(n)
        seen = []
        with self.assertRaises(PermissionError):
            ExecutionGate(self.store).dispatch(action, (), seen.append)
        self.assertEqual(seen, [])

    def test_repeated_call_id_rejected_after_restart(self):
        n = self.store.ingest("task", "data", "user")
        action, cap = self.action(n)
        seen = []
        ExecutionGate(self.store).dispatch(action, (cap,), seen.append)
        self.store.close()
        self.store = ProvenanceStore(self.path)
        with self.assertRaises(sqlite3.IntegrityError):
            ExecutionGate(self.store).dispatch(action, (cap,), seen.append)
        self.assertEqual(len(seen), 1)

    def test_quarantine_closure_preserves_independent_branch(self):
        user, ext, mixed, copy, other = self.fixture()
        affected = self.store.quarantine((ext,), "fixture root")
        self.assertEqual(set(affected), {ext, mixed, copy})
        self.assertEqual(self.store.get(other)["status"], "active")
        self.assertEqual(self.store.get(user)["status"], "active")
        self.assertFalse(self.store.verify(self.store.envelope(copy), "Copy"))

    def test_new_descendant_of_quarantined_state_rejected(self):
        _, ext, mixed, _, _ = self.fixture()
        self.store.quarantine((ext,), "test")
        with self.assertRaises(ValueError):
            self.store.derive("new", "copy", (mixed,))

    def test_stale_checked_action_rechecked_on_dispatch(self):
        _, ext, _, copy, _ = self.fixture()
        action, cap = self.action(copy)
        gate = ExecutionGate(self.store)
        self.assertTrue(gate.check(action, (cap,)).allowed)
        self.store.quarantine((ext,), "late alert")
        with self.assertRaises(PermissionError):
            gate.dispatch(action, (cap,), lambda _: self.fail("must not execute"))

    def test_rebuild_creates_new_version_keeps_old_quarantined(self):
        user, ext, mixed, _, _ = self.fixture()
        self.store.quarantine((ext,), "test")
        new = self.store.rebuild(mixed, "Clean fixture", (user,))
        self.assertEqual(self.store.get(new)["version"], 2)
        self.assertEqual(self.store.get(mixed)["status"], "quarantined")
        self.assertTrue(self.store.verify(self.store.envelope(new), "Clean fixture"))

    def test_rebuild_does_not_promote_external_origin(self):
        ext = self.store.ingest("bad", "bad")
        clean_external = self.store.ingest("verified-page", "benign external text")
        self.store.quarantine((ext,), "test")
        new = self.store.rebuild(ext, "benign text", (clean_external,))
        self.assertEqual(self.store.get(new)["origins"], ["external"])

    def test_unrelated_root_cannot_be_repaired_from_call(self):
        _, _, _, copy, other = self.fixture()
        action, cap = self.action(copy)
        ExecutionGate(self.store).dispatch(action, (cap,), lambda _: None)
        with self.assertRaises(ValueError):
            RepairPlanner(self.store).apply(action.call_id, (other,), "unrelated")

    def test_call_ancestry_and_repair_across_restart(self):
        user, ext, mixed, copy, _ = self.fixture()
        action, _ = self.action(copy)
        with self.assertRaises(PermissionError):
            ExecutionGate(self.store).dispatch(action, (), lambda _: None)
        self.store.close()
        self.store = ProvenanceStore(self.path)
        repair = RepairPlanner(self.store)
        self.assertEqual(repair.candidates(action.call_id), {user, ext, mixed, copy})
        self.assertEqual(set(repair.apply(action.call_id, (ext,), "fixture evidence")), {ext, mixed, copy})

    def test_demo_reports_mechanism_only(self):
        result = run(Path(self.tmp.name) / "demo.sqlite")
        self.assertEqual(result["model_calls"], 0)
        self.assertFalse(result["unauthorized_delivered"])
        self.assertTrue(result["unrelated_state_preserved"])
        self.assertTrue(result["recovered_local_action"])
        self.assertFalse(result["old_copy_retrievable"])


if __name__ == "__main__":
    unittest.main()
