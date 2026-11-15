"""Validate coverage and publish non-sensitive summaries of the AgentDojo evaluation."""

import argparse
import csv
from collections import Counter
import hashlib
import json
from pathlib import Path
from statistics import median

SUITES = {
    "workspace": (40, range(6)),
    "travel": (20, range(7)),
    "banking": (16, range(9)),
    "slack": (21, range(1, 6)),
}


def csv_file(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def main(root, out):
    out.mkdir(parents=True, exist_ok=True)
    traces = []

    def load(folder):
        recs = {}
        for f in sorted((root / folder).rglob("*.json")):
            r = json.loads(f.read_bytes())
            key = (r["suite"], r["task"], r["injection"], r.get("arm"))
            assert key not in recs, key
            recs[key] = r
            events = []
            for ev in r["events"]:
                if "answer" in ev:
                    events.append({"answer_sha256": digest(ev["answer"])})
                else:
                    events.append(
                        {
                            **{k: v for k, v in ev.items() if k != "args"},
                            "args_sha256": digest(ev["args"]),
                        }
                    )
            traces.append(
                dict(
                    stage=folder,
                    suite=key[0],
                    task=key[1],
                    injection=key[2],
                    arm=key[3],
                    events=events,
                    api_errors=r.get("api_errors", []),
                    usage=r["usage"],
                )
            )
        return recs

    first = load("first")
    repeat = load("repeats")
    controlled = load("controlled")
    ref_rows = json.loads((root / "reference.json").read_bytes())
    reference = {(x["suite"], x["task"], x["injection"]): x for x in ref_rows}
    coverage = []
    normal = []
    controls = []
    security = []
    matched = Counter()

    def metrics(r):
        return dict(
            status=r["status"],
            error=r.get("error"),
            utility=r.get("utility"),
            seconds=r["seconds"],
            api_calls=r["calls"],
            tokens=sum(u.get("total_tokens", 0) for u in r["usage"]),
            tools=sum(e.get("dispatched", False) for e in r["events"]),
            denied=sum(e.get("gate") == "outside_host_grant" for e in r["events"]),
        )

    def audit(k, r):
        baseline = reference[k]
        assert r["fixture_hash"] == baseline["fixture_hash"]
        boundary = baseline["clean_chars"] + 1
        return dict(
            status=r["status"],
            error=r.get("error"),
            slot=r["slot"],
            fixture_hash=r["fixture_hash"],
            verdict=r.get("verdict"),
            overlaps_goal=any(a + n > boundary for a, n in r.get("evidence_spans", [])),
            evidence_spans=json.dumps(r.get("evidence_spans", [])),
            reference_detected=baseline["reference_detected"],
            reference_safe_score=baseline["reference_safe_score"],
            repair_verified=r.get("repair_verified"),
            continuation_utility=r.get("continuation_utility"),
        )

    for d, (count, targets) in SUITES.items():
        for n in range(count):
            u = f"user_task_{n}"
            for stage, mapping in (("first", first), ("repeat", repeat)):
                for arm in ["plain", "gate"]:
                    key = (d, u, None, arm)
                    if stage == "first" or key in mapping:
                        normal.append(
                            dict(
                                suite=d,
                                task=u,
                                arm=arm,
                                stage=stage,
                                **metrics(mapping[key]),
                            )
                        )
            a, b = [first[d, u, None, arm] for arm in ["plain", "gate"]]
            assert a["status"] == b["status"] == "scored"
            assert ((d, u, None, "gate") in repeat) == (a["utility"] != b["utility"])
            matched[a["utility"], b["utility"]] += 1
            controls.append(
                dict(
                    suite=d, task=u, **audit((d, u, None), controlled[d, u, None, None])
                )
            )
            for i in targets:
                iid = f"injection_task_{i}"
                k = (d, u, iid)
                if (*k, None) in controlled:
                    r = controlled[*k, None]
                    coverage.append(
                        dict(
                            suite=d,
                            task=u,
                            injection=iid,
                            mode="controlled_fixture",
                            reason=r["original_not_run_reason"],
                            **audit(k, r),
                        )
                    )
                else:
                    record = dict(
                        suite=d,
                        task=u,
                        injection=iid,
                        mode="official_direct",
                        reason="",
                    )
                    for arm in ["plain", "gate"]:
                        r = first[*k, arm]
                        record.update(
                            {
                                arm + "_" + name: value
                                for name, value in metrics(r).items()
                            }
                        )
                        record[arm + "_goal"] = r.get("goal_reached")
                        record[arm + "_exposed"] = r.get("goal_text_observed")
                        if d == "travel" and i == 6:
                            record[arm + "_clean_hotel_mention"] = any(
                                "Riverside View Hotel" in e.get("answer", "")
                                for e in first[d, u, None, arm]["events"]
                            )
                        security.append(
                            dict(
                                suite=d,
                                task=u,
                                injection=iid,
                                arm=arm,
                                **metrics(r),
                                goal=r.get("goal_reached"),
                                exposed=r.get("goal_text_observed"),
                            )
                        )
                    coverage.append(record)
    assert (
        len(coverage) == 629
        and len(first) == 514
        and len(controlled) == 566
        and len(reference) == 566
    )
    csv_file(out / "normal.csv", normal)
    csv_file(out / "security-629.csv", coverage)
    csv_file(out / "benign-episodes.csv", security)
    csv_file(out / "negative-controls.csv", controls)
    with (out / "trace-index.jsonl").open("w", encoding="utf-8") as f:
        for r in traces:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")

    def clean_summary(rows):
        return dict(
            n=len(rows),
            passed=sum(x["utility"] is True for x in rows),
            denied_cases=sum(x["denied"] > 0 for x in rows),
            seconds_median=median(x["seconds"] for x in rows),
            tokens=sum(x["tokens"] for x in rows),
        )

    c = [r for r in coverage if r["mode"] == "controlled_fixture"]

    def detections(rows):
        return dict(
            n=len(rows),
            unique=len({r["fixture_hash"] for r in rows}),
            ariadne=sum(r["verdict"] == "polluted" for r in rows),
            unknown=sum(r["verdict"] == "unknown" for r in rows),
            errors=sum(r["status"] == "error" for r in rows),
            reference=sum(r["reference_detected"] for r in rows),
            additional=sum(
                r["verdict"] == "polluted" and not r["reference_detected"] for r in rows
            ),
            reverse=sum(
                r["verdict"] != "polluted" and r["reference_detected"] for r in rows
            ),
        )

    summary = dict(
        protocol="AgentDojo 0.1.34 / v1 / DeepSeek Flash",
        normal={},
        security={},
        domain={},
        repeat={},
        paired={str(k): v for k, v in matched.items()},
        controlled=detections(c),
        negative=detections(controls),
        repaired=sum(x["repair_verified"] is True for x in c),
        continued=sum(x["continuation_utility"] is not None for x in c),
        resumed_pass=sum(x["continuation_utility"] is True for x in c),
        overlaps=sum(x["overlaps_goal"] for x in c),
        calls=sum(
            r["calls"] for group in (first, repeat, controlled) for r in group.values()
        ),
        tokens=sum(
            sum(u.get("total_tokens", 0) for u in r["usage"])
            for group in (first, repeat, controlled)
            for r in group.values()
        ),
    )
    for arm in ["plain", "gate"]:
        subset = [r for r in normal if r["arm"] == arm]
        summary["normal"][arm] = clean_summary(
            [r for r in subset if r["stage"] == "first"]
        )
        summary["repeat"][arm] = clean_summary(
            [r for r in subset if r["stage"] == "repeat"]
        )
        sec = [r for r in security if r["arm"] == arm]
        summary["security"][arm] = dict(
            n=len(sec),
            scored=sum(r["status"] == "scored" for r in sec),
            utility=sum(r["utility"] is True for r in sec),
            goal=sum(r["goal"] is True for r in sec),
            exposed=sum(r["exposed"] is True for r in sec),
            already_mentioned=sum(
                r.get(arm + "_clean_hotel_mention", False)
                and r.get(arm + "_goal", False)
                for r in coverage
            ),
        )
    for d, (n, _) in SUITES.items():
        summary["domain"][d] = [n] + [
            sum(
                r["utility"]
                for r in normal
                if r["suite"] == d and r["arm"] == a and r["stage"] == "first"
            )
            for a in ("plain", "gate")
        ]
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    main(args.root, args.output)
