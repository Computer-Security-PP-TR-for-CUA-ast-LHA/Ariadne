"""Cross-module contracts using the real label and recovery databases."""
from pathlib import Path
from uuid import uuid4
import unittest
from unittest.mock import patch

from cua_guard.label_bridge import LabelRecoveryBridge, LabelRepairProjection
from cua_guard.label_store import PersistentLabelStore
from cua_guard.recovery import RecoveryCoordinator, SQLiteRecoveryStore
from cua_guard.recovery.contracts import RecoveryError, RecoveryRequest, Validation
from cua_guard.recovery.graph import VersionGraph


class Cleaner:
    identity = "fixture-cleaner/1"

    def repair(self, old, inputs, task):
        return (old.content.replace("; INJECT", ""),)


class Validator:
    identity = "fixture-validator/1"

    def validate(self, old, outputs, task):
        return Validation(True, True, "fixture assertion")


class LabelBridgeTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / (".label-bridge-" + str(uuid4()))
        self.root.mkdir()
        self.labels = PersistentLabelStore(self.root / "primary.sqlite",
                                           self.root / "mirror.sqlite", scope_id="case")
        self.recovery = SQLiteRecoveryStore(self.root / "recovery.sqlite")
        self.bridge = LabelRecoveryBridge(self.labels, self.recovery)

    def tearDown(self):
        self.labels.close()
        for path in self.root.iterdir():
            path.unlink()
        self.root.rmdir()

    def test_normal_capture_has_one_revision_and_real_parent_edges(self):
        task = self.bridge.start_session("session", "Summarize")
        page = self.bridge.capture("session", "page", "fact", channel="external")
        summary = self.bridge.capture("session", "memory", "fact", parents=(task, page))
        self.assertEqual(self.bridge.assert_ready(), 3)
        snapshot = self.recovery.snapshot("case")
        self.assertEqual(snapshot.revision, self.labels.revision())
        self.assertEqual({v.version_id for v in snapshot.versions}, {task, page, summary})
        self.assertEqual(self.labels.read(summary).parents, (task, page))
        handoff = self.bridge.export_graph_handoff()
        self.assertEqual(handoff["ledger_revision"], 3)
        self.assertEqual([e["record_id"] for e in handoff["events"]],
                         [task, page, summary])

    def test_interrupted_projection_replays_from_mirrored_outbox(self):
        self.bridge.start_session("session", "Summarize")
        with patch.object(self.recovery, "append", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                self.bridge.capture("session", "page", "fact")
        self.assertEqual(self.labels.revision(), 2)
        self.assertEqual(self.recovery.snapshot("case").revision, 1)
        with self.assertRaises(RecoveryError):
            self.bridge.assert_ready()
        self.assertEqual(self.bridge.reconcile(), 2)
        self.assertEqual(self.bridge.assert_ready(), 2)

    def test_repair_publishes_to_both_label_files_before_reopening(self):
        self.bridge.start_session("session", "Use fact")
        root = self.bridge.capture("session", "page", "fact; INJECT")
        child = self.bridge.capture("session", "memory", "fact; INJECT", parents=(root,))
        good = self.bridge.capture("session", "other", "normal fact")
        request = RecoveryRequest("repair-1", "case", "Use fact", (root,), ("observed-injection",))
        projection = LabelRepairProjection(self.labels, self.bridge.recovery,
                                           request.request_id)
        result = RecoveryCoordinator(self.bridge.recovery, Cleaner(), Validator(), projection,
                                     graph=self.bridge).recover(request)
        self.assertEqual(result["outcome"], "ready", result.get("error"))
        self.assertEqual(self.bridge.assert_ready(), self.recovery.snapshot("case").revision)
        self.assertEqual(self.labels.read(root).status, "superseded")
        self.assertEqual(self.labels.read(child).status, "superseded")
        self.assertEqual(self.labels.read(good).status, "active")
        self.assertFalse(self.labels.verify(root, "fact; INJECT"))
        self.assertEqual(self.labels.content(result["mapping"][root][0]), "fact")
        self.assertEqual(self.labels.content(result["mapping"][child][0]), "fact")
        handoff = self.bridge.export_graph_handoff()
        self.assertEqual(handoff["repair_commits"][0]["mapping"], result["mapping"])
        self.assertEqual(set(self.bridge.snapshot("case").edges),
                         set(self.recovery.snapshot("case").edges))
        self.labels.close()
        self.labels = PersistentLabelStore(self.root / "primary.sqlite",
                                           self.root / "mirror.sqlite", scope_id="case")
        self.assertEqual(self.labels.scan_consistency(), 6)

    def test_recovery_quarantine_is_committed_in_both_label_files_before_repair(self):
        self.bridge.start_session("session", "Use fact")
        root = self.bridge.capture("session", "page", "fact; INJECT")
        request = RecoveryRequest("repair-isolation", "case", "Use fact", (root,),
                                  ("observed-injection",))

        class CheckingCleaner(Cleaner):
            def repair(inner, old, inputs, task):
                self.assertEqual(self.labels.read(root).status, "quarantined")
                self.assertEqual(self.labels.revision(), self.recovery.snapshot("case").revision)
                return super().repair(old, inputs, task)

        projection = LabelRepairProjection(self.labels, self.bridge.recovery,
                                           request.request_id)
        result = RecoveryCoordinator(self.bridge.recovery, CheckingCleaner(), Validator(),
                                     projection, graph=self.bridge).recover(request)
        self.assertEqual(result["outcome"], "ready", result.get("error"))
        kinds = [event["kind"] for event in self.labels.outbox()]
        self.assertEqual(kinds[-2:], ["repair_quarantine", "repair_publish"])
        self.assertEqual(self.labels.read(root).status, "superseded")

    def test_interrupted_quarantine_replays_identical_plan_from_durable_job(self):
        self.bridge.start_session("session", "Use fact")
        root = self.bridge.capture("session", "page", "fact; INJECT")
        request = RecoveryRequest("repair-replay", "case", "Use fact", (root,),
                                  ("observed-injection",))
        port = self.bridge.recovery
        port.reserve(request, {"fixture": "replay"})
        plan = VersionGraph(self.bridge.snapshot("case")).plan(request)
        base = self.labels.revision()
        with patch.object(self.labels, "quarantine_repair", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                port.quarantine(request, plan)
        self.assertEqual(self.labels.revision(), base)
        self.assertEqual(self.recovery.snapshot("case").revision, base + 1)
        self.assertEqual(port.job("case", request.request_id)["state"], "quarantined")
        self.assertEqual(self.labels.read(root).status, "quarantined")
        self.assertEqual(self.labels.revision(), base + 1)
        self.assertEqual(port.job("case", request.request_id)["revision"], base + 1)


if __name__ == "__main__":
    unittest.main()
