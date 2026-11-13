"""The live label-to-graph adapter rejects omitted host writes and ID drift."""
from pathlib import Path
from uuid import uuid4
import unittest
from unittest.mock import patch

from cua_guard.label_bridge import LabelRecoveryBridge
from cua_guard.label_provenance import LabelProvenancePort, memory_id
from cua_guard.label_runtime import LabelSession
from cua_guard.label_store import PersistentLabelStore
from cua_guard.provenance import EdgeType
from cua_guard.recovery import SQLiteRecoveryStore
from cua_guard.recovery.contracts import RecoveryError
from cua_guard.recovery.contracts import Validation


class Cleaner:
    identity = "graph-port-test-cleaner/1"

    def repair(self, old, inputs, task):
        return (old.content.replace("; INJECT", ""),)


class Validator:
    identity = "graph-port-test-validator/1"

    def validate(self, old, outputs, task):
        return Validation(True, True, "fixture")


class LabelProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).parent / (".label-provenance-" + str(uuid4()))
        self.root.mkdir()
        self.labels = PersistentLabelStore(self.root / "primary.sqlite",
                                           self.root / "mirror.sqlite", scope_id="case")
        self.recovery = SQLiteRecoveryStore(self.root / "recovery.sqlite")
        self.bridge = LabelRecoveryBridge(self.labels, self.recovery)
        self.port = LabelProvenancePort(self.bridge, "Summarize the mail")
        self.session = LabelSession(self.bridge, None, "Summarize the mail",
                                    session_id="session", graph=self.port)

    def tearDown(self):
        self.labels.close()
        for path in self.root.iterdir():
            path.unlink()
        self.root.rmdir()

    def test_real_versions_and_reads_project_to_recovery(self):
        page = self.session.capture("email", "Meeting Friday at 14:00")
        summary = self.session.capture("summary", "Friday 14:00",
                                       tuple(self.session.context))
        self.session.messages()
        graph = self.port.build()
        self.assertEqual(graph.coverage, "complete_within_scope")
        self.assertIn(EdgeType.DERIVE.value,
                      graph.edge_types(memory_id(page), memory_id(summary)))
        self.assertEqual(self.port.snapshot("case"), self.bridge.label_snapshot())
        self.assertEqual(len([n for n in graph.nodes.values()
                              if n.node_kind.value == "memory"]), 3)

    def test_missing_host_write_is_not_silently_inferred(self):
        self.bridge.capture("session", "unhooked", "fact")
        with self.assertRaises(RecoveryError) as caught:
            self.port.snapshot("case")
        self.assertEqual(caught.exception.code, "missing_host_write")

    def test_post_repair_graph_failure_suspends_scope(self):
        self.session.capture("email", "fact; INJECT")
        self.session.detector = lambda task, text: (
            {"verdict": "polluted", "evidence": ["; INJECT"]}
            if "; INJECT" in text else {"verdict": "clean", "evidence": []})
        self.session.repair_backend = Cleaner()
        self.session.validator = Validator()
        with patch.object(self.port, "on_recovery_commit",
                          side_effect=RecoveryError("invalid_graph")):
            with self.assertRaises(PermissionError):
                self.session.screen()
        self.assertTrue(self.session.blocked)
        self.assertFalse(self.recovery.ready("case", self.labels.revision()))


if __name__ == "__main__":
    unittest.main()
