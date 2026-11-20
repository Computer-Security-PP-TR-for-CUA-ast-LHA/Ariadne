"""Offline extraction must preserve missing scores and reject duplicate episodes."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "agentdojo_diagnose", Path(__file__).resolve().parents[1] / "scripts/agentdojo_diagnose.py")
diagnose = importlib.util.module_from_spec(spec)
spec.loader.exec_module(diagnose)


class DiagnosisTests(unittest.TestCase):
    def fixture(self, root):
        for stage in ("first", "repeats", "controlled"):
            (root / stage).mkdir()
            row = dict(suite="workspace", task="user_task_0", injection=None,
                       arm="plain", status="scored", utility=True, events=[])
            if stage == "controlled":
                row.update(status="checked", repair_verified=True,
                           continuation_utility=False, utility=None)
            (root / stage / "one.json").write_text(json.dumps(row))
        row.update(arm="gate", status="error", repair_verified=None,
                   continuation_utility=None)
        (root / "first" / "gate.json").write_text(json.dumps(row))

    def test_missing_scores_are_not_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            summary, rows, pairs, manifest = diagnose.summarize(root)
            self.assertEqual(summary["clean_scored_pairs"], 0)
            self.assertIsNone(pairs[0]["gate_utility"])
            self.assertEqual(summary["continuation"], {"failed_without_denial": 1})
            self.assertTrue(all(r["goal_reached"] is None for r in rows))
            self.assertEqual(len(manifest), 4)

    def test_duplicate_and_missing_batch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            duplicate = root / "first" / "duplicate.json"
            duplicate.write_bytes((root / "first" / "one.json").read_bytes())
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                diagnose.summarize(root)
            duplicate.unlink()
            (root / "controlled" / "one.json").unlink()
            with self.assertRaisesRegex(ValueError, "Missing records"):
                diagnose.summarize(root)


if __name__ == "__main__":
    unittest.main()
