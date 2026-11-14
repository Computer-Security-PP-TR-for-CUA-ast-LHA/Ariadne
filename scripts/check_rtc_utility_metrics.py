"""Check the pinned RTC-Bench normal-task metrics with controlled getter outputs."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

PIN = "a05b8bd04629e19a9a06bf04f8e0c5b53549d16c"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    head = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if head != PIN:
        raise ValueError("RTC revision mismatch")
    sys.path.insert(0, str(upstream))
    from desktop_env.evaluators import metrics

    examples = upstream / "evaluation_examples"
    groups = defaultdict(list)
    with ZipFile(examples / "RedTeamCUA_configs.zip") as archive:
        for platform, ids in json.loads((examples / "test_all.json").read_bytes()).items():
            for case_id in ids:
                record = json.loads(archive.read(f"examples/{platform}/{case_id}.json"))
                assert (record["id"], record["platform"]) == (case_id, platform)
                key = platform, json.dumps(record["evaluator"], sort_keys=True)
                groups[key].append(case_id)
    controls = {"check_path_existence": (1, 0), "check_htop_version": ("", "htop: not found"),
                "check_nodejs": ("", "node: not found"), "check_termcolor_version": ("termcolor 2.0", ""),
                "check_git_config": ("Peter", "")}
    results = []
    for (platform, spec), ids in sorted(groups.items()):
        config = json.loads(spec)
        func = config["func"]
        metric = getattr(metrics, func)
        if func == "must_include":
            rules = config["expected"]["rules"]
            positive, negative = metric(rules["expected"], rules), metric("", rules)
        else:
            yes, no = controls[func]
            positive, negative = metric(yes), metric(no)
        results.append({"platform":platform, "normal_evaluator":config, "case_count":len(ids),
                        "example_id":ids[0], "positive":positive, "negative":negative})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"kind":"metric_controls_only", "revision":head,
                                       "gui_episodes":0, "controls":results}, indent=2), encoding="utf-8")
    if not all(r["positive"] == 1 and r["negative"] == 0 for r in results):
        raise SystemExit("Unexpected utility metric control result")
    print(f"{len(results)} evaluator configurations, {sum(len(ids) for ids in groups.values())} indexed cases")


if __name__ == "__main__":
    main()
