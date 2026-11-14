"""Run reviewed original upstream checks; never start a model or real tool.

The only live remedy permitted here is OpenAPPA's built-in email redactor. The
full config is checked before execution so an added remote/model/command hook
cannot silently turn this offline check into a paid or external run.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib

from cua_guard.upstreams import UpstreamRegistry
from demo_reused_authority import run as authority_demo


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream-root")
    parser.add_argument("--tools-root")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    registry = UpstreamRegistry(args.upstream_root)
    output = args.output or registry.root.parent / "runs/reuse/offline-checks.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    checks, sources = [], []
    for name, source in registry.sources.items():
        try:
            registry.verify(name)
            sources.append({"name": name, "commit": source["commit"], "verified": True})
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            sources.append({"name": name, "verified": False, "error": str(exc)})

    def execute(name, command, validate, expected_returncode=0):
        start = time.monotonic()
        try:
            completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                       errors="replace", timeout=60)
            checks.append({"name": name, "passed": completed.returncode == expected_returncode and validate(completed),
                           "expected_returncode": expected_returncode,
                           "returncode": completed.returncode, "seconds": round(time.monotonic()-start, 3),
                           "stdout": completed.stdout, "stderr": completed.stderr})
        except (OSError, subprocess.SubprocessError) as exc:
            checks.append({"name": name, "passed": False, "error": str(exc)})

    try:
        tma = registry.verify("mem-inv-bench")
        for script in ("test_tma.py", "test_vouchers.py"):
            execute("TMA-NM/"+script, [sys.executable, str(tma / "code" / script)],
                    lambda r: "ALL " in r.stdout and not re.search(r"\[FAIL\]|FAILURES:", r.stdout))
        result = authority_demo(registry.root)
        checks.append({"name": "TMA-NM/original_gate_and_recovery_adapter", "passed": True, "result": result})
    except (OSError, RuntimeError, AssertionError, subprocess.SubprocessError) as exc:
        checks.append({"name": "TMA-NM/integration", "passed": False, "error": str(exc)})

    try:
        appa_root = registry.verify("OpenAPPA")
        binary = registry.openappa(args.tools_root)
        cases = ("untrusted-web-content", "three-trust-ranks", "secret-stays-inside",
                 "backup-before-deploy", "redact-before-sending")
        for case in cases:
            directory = appa_root / "examples/tests" / case
            config = directory / "appa.toml"
            data = tomllib.loads(config.read_text(encoding="utf-8"))
            externals = dict(data.get("externals", {}))
            externals.pop("timeout_ms", None)
            externals.pop("max_body_bytes", None)
            redaction = case == "redact-before-sending"
            allowed = {"sanitizers": {"redactor": {"builtin": "redact-email"}}} if redaction else {}
            if externals != allowed:
                raise RuntimeError(f"{case}: configuration is no longer an offline-only fixture")
            command = [str(binary), "replay", "--config", str(config), "--json"]
            command.append(str(directory / (case + ".appa")))

            def valid_replay(completed):
                rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
                summary = rows[-1]["summary"]
                return (summary == {"ok": 1, "failed": 0, "cannot_run": 0}
                        and len(rows) > 1 and all(row["outcome"] == "passed" for row in rows[:-1]))

            suffix = "/offers_only_stand_in" if redaction else ""
            execute("OpenAPPA/"+case+suffix, command, valid_replay)
            if redaction:
                # Preserve the original fixture's observed live outcome. Do not
                # infer its cause, call it semantic repair, or silently replace
                # the original fixture with one that happens to pass.
                original_live = command[:-1] + ["--live-remedies", command[-1]]
                execute("OpenAPPA/original_live_redaction_is_not_released", original_live,
                        lambda r: "cannot_run" in r.stdout and "derivation was not usable" in r.stdout,
                        expected_returncode=2)
                fixture = Path(__file__).resolve().parents[1] / "tests/upstream/openappa/actual-redaction.appa"
                actual = command[:-1] + ["--live-remedies", str(fixture)]

                def valid_redaction(completed):
                    if not valid_replay(completed):
                        return False
                    rows = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
                    return any(row.get("answered_by") == "live" and row.get("rewritten")
                               and "bob@example.test" not in json.dumps(row["rewritten"])
                               for row in rows[:-1])

                execute("OpenAPPA/actual_builtin_redaction_integration", actual, valid_redaction)
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        checks.append({"name": "OpenAPPA/integration", "passed": False, "error": str(exc)})

    report = {"checked_on": "2026-11-01", "model_calls": 0, "real_tools_executed": False,
              "sources": sources, "checks": checks,
              "passed": all(x["passed"] for x in checks) and all(x["verified"] for x in sources),
              "limits": "Original offline policy/mechanism checks; not live-model benchmark reproduction."}
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(output), "checks": [{"name": x["name"], "passed": x["passed"]}
                                                        for x in checks], "passed": report["passed"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
