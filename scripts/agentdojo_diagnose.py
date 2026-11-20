"""Offline triage of archived midterm logs; no model, benchmark or network imports.

Outputs contain identifiers, counts and hashes, not prompts, arguments or responses.
Association with a denied call is not a causal false-positive classification.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def summarize(root):
    rows, manifest, seen = [], [], set()
    for stage in ("first", "repeats", "controlled"):
        files = sorted((root / stage).rglob("*.json"))
        if not files:
            raise ValueError(f"Missing records: {stage}")
        for path in files:
            raw = path.read_bytes()
            row = json.loads(raw)
            key = (stage, row["suite"], row["task"], row["injection"], row.get("arm"))
            if key in seen:
                raise ValueError(f"Duplicate episode: {key}")
            seen.add(key)
            if not isinstance(row.get("events"), list):
                raise ValueError(f"Missing events: {path}")
            denied = [e for e in row["events"] if e.get("dispatched") is False]
            item = {
                "stage": stage, "suite": row["suite"], "task": row["task"],
                "injection": row["injection"], "arm": row.get("arm"),
                "status": row["status"], "utility": row.get("utility"),
                "goal_reached": row.get("goal_reached"),
                "repair_verified": row.get("repair_verified"),
                "continuation_utility": row.get("continuation_utility"),
                "fixture_hash": row.get("fixture_hash"),
                "denied_calls": len(denied),
                "denial_reasons": dict(Counter(e.get("gate", "unreported") for e in denied)),
                "denied_tools": dict(Counter(e["tool"] for e in denied)),
                "first_denial_turn": denied[0].get("turn") if denied else None,
                "api_error_count": len(row.get("api_errors", [])),
                "api_errors_recorded": "api_errors" in row,
                "source": path.relative_to(root).as_posix(),
            }
            rows.append(item)
            manifest.append({"source": item["source"], "sha256": hashlib.sha256(raw).hexdigest()})
    clean = {(r["suite"], r["task"], r["arm"]): r for r in rows
             if r["stage"] == "first" and r["injection"] is None}
    pairs = []
    for suite, task in sorted({(k[0], k[1]) for k in clean}):
        plain, gate = (clean.get((suite, task, arm)) for arm in ("plain", "gate"))
        valid = bool(plain and gate and plain["status"] == gate["status"] == "scored"
                     and type(plain["utility"]) is bool and type(gate["utility"]) is bool)
        pairs.append({"suite": suite, "task": task, "paired_scored": valid,
                      "plain_utility": plain["utility"] if plain else None,
                      "gate_utility": gate["utility"] if gate else None,
                      "gate_denied_calls": gate["denied_calls"] if gate else None})
    repaired = [r for r in rows if r["stage"] == "controlled" and r["repair_verified"] is True]
    continuation = Counter()
    for row in repaired:
        outcome = {True: "passed", False: "failed", None: "unscored"}[row["continuation_utility"]]
        continuation[f"{outcome}_{'with' if row['denied_calls'] else 'without'}_denial"] += 1
    reasons = Counter()
    for row in rows:
        reasons.update(row["denial_reasons"])
    summary = {
        "scope": "historical logs only; denial association is not causal attribution",
        "records": len(rows), "by_stage": dict(Counter(r["stage"] for r in rows)),
        "status": dict(Counter(r["status"] for r in rows)),
        "clean_pairs": len(pairs),
        "clean_scored_pairs": sum(p["paired_scored"] for p in pairs),
        "clean_outcomes": dict(Counter(
            f"plain_{p['plain_utility']}_gate_{p['gate_utility']}"
            for p in pairs if p["paired_scored"])),
        "denial_reasons_by_call": dict(reasons),
        "repair_verified": len(repaired), "continuation": dict(continuation),
    }
    return summary, rows, pairs, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    if output == root or root in output.parents:
        parser.error("Output must be outside the immutable input archive")
    summary, rows, pairs, manifest = summarize(root)
    output.mkdir(parents=True, exist_ok=True)
    for name, data in (("summary.json", summary), ("source-manifest.json", manifest)):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, data in (("episodes.jsonl", rows), ("clean-pairs.jsonl", pairs)):
        (output / name).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in data), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
