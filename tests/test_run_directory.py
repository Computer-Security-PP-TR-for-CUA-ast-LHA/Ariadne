"""Verify GUI result paths and terminal status without starting a virtual machine."""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from cua_guard import redteamcua


class RunDirectoryTests(unittest.TestCase):
    def test_second_attempt_does_not_overwrite_first_attempt(self):
        desktop = ModuleType("desktop_env.desktop_env")
        desktop.DesktopEnv = MagicMock()
        runner = ModuleType("lib_run_single")
        def simulate(agent, kind, env, example, limit, task, options, directory, scores):
            (Path(directory) / "result.txt").write_text("1\n")
            agent.session = SimpleNamespace(repairs=[], alerts=[])
        runner.run_single_example = simulate
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "case.json"
            fixture.write_text(json.dumps({"id":"example","instruction":"Read the calendar."}))
            output = root / "output"
            argv = ["runner","--upstream",tmp,"--vm-path","unused","--example",str(fixture),"--output",str(output)]
            with (patch.object(sys, "argv", argv), patch.object(sys, "path", list(sys.path)),
                  patch.dict(sys.modules, {"desktop_env.desktop_env":desktop, "lib_run_single":runner}),
                  patch.object(redteamcua.subprocess, "check_output", return_value=redteamcua.REVISION),
                  patch.object(redteamcua.DeepSeekClient, "from_env", return_value=SimpleNamespace(model="test",usage={}))):
                redteamcua.main()
                first = next(output.iterdir())
                desktop.DesktopEnv.side_effect = RuntimeError("simulated initialization failure")
                with self.assertRaises(RuntimeError):
                    redteamcua.main()
            second, = set(output.iterdir()) - {first}
            self.assertEqual((first / "result.txt").read_text(), "1\n")
            self.assertEqual(json.loads((first / "ariadne.json").read_text())["status"], "completed")
            self.assertEqual(json.loads((second / "ariadne.json").read_text())["status"], "failed")
            self.assertFalse((second / "result.txt").exists())
