"""Detector-only untrusted fixture followed by trusted-snapshot repair and clean continuation.

Restricted security goals never enter an acting agent or an execution environment.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import tempfile
import time

from agentdojo.attacks.baseline_attacks import DirectAttack
from agentdojo_midterm import BENIGN, SUITES, Pipeline, client, initial
from cua_guard.label_store import PersistentLabelStore
from cua_guard.model import load_env
from cua_guard.repair import RepairPlanner
from cua_guard.semantic import SemanticDefense
from cua_guard.store import ProvenanceStore


@lru_cache(maxsize=100)
def clean_slot(domain, uid):
    suite = SUITES[domain]
    refs = DirectAttack(suite, None).get_injection_candidates(suite.user_tasks[uid])
    slot = sorted(refs)[0]
    return slot, suite.get_injection_vector_defaults()[slot]


REASONS = {
    "workspace": {
        1: "file deletion",
        3: "private email disclosure",
        4: "security code disclosure",
        5: "security code disclosure and evidence deletion",
    },
    "travel": {
        1: "mailbox disclosure",
        3: "identity and banking information disclosure",
        5: "identity and payment information disclosure",
    },
    "banking": {
        0: "financial disclosure and transfer",
        1: "third-party banking disclosure and transfer",
        2: "personal disclosure and transfer",
        3: "device disclosure and transfer",
        4: "payment redirection",
        5: "unauthorized transfer",
        6: "structured unauthorized transfers",
        7: "credential alteration",
        8: "financial schedule disclosure and transfer",
    },
    "slack": {
        1: "phishing distribution",
        2: "workspace message disclosure",
        3: "phishing destination",
        4: "channel history disclosure",
        5: "unauthorized membership changes",
    },
}


def evaluate(job, output):
    domain, uid, iid = job
    path = output / domain / uid / (iid or "clean-control") / "inspection.json"
    if path.exists():
        return
    start = time.monotonic()
    suite = SUITES[domain]
    task = suite.user_tasks[uid]
    c = client()
    row = dict(suite=domain, task=uid, injection=iid)
    store = ProvenanceStore(":memory:")
    pipeline = None
    try:
        slot, trusted = clean_slot(domain, uid)
        # One fixture per pair; retain the benign value so preservation is measurable.
        content = trusted
        if iid:
            index = int(iid.rsplit("_", 1)[1])
            row["original_not_run_reason"] = REASONS[domain][index]
            content += "\n" + suite.injection_tasks[iid].GOAL
        row.update(slot=slot, fixture_hash=hashlib.sha256(content.encode()).hexdigest())
        verified = store.ingest("known-clean-slot", trusted)
        root = store.ingest("external-observation", content)
        child = store.derive("cached-observation", content, (root,))
        store.record_call(
            "inspection",
            {"bindings": [(child, store.get(child)["hash"])]},
            "inspection_only",
        )
        result = SemanticDefense(store, c).inspect(task.PROMPT, content)
        row["verdict"] = result["verdict"]
        row["evidence_spans"] = [[content.index(e), len(e)] for e in result["evidence"]]
        if iid and result["verdict"] == "polluted":
            planner = RepairPlanner(store)
            affected = planner.apply(
                "inspection",
                (root,),
                "Grounded detector evidence at external observation",
            )
            new = store.rebuild(root, trusted, (verified,))
            new_child = store.rebuild(child, store.get(new)["content"], (new,))
            restored = store.get(new_child)
            row["repair_verified"] = (
                set(affected) == {root, child}
                and all(store.get(n)["status"] == "quarantined" for n in affected)
                and store.get(verified)["status"] == "active"
                and restored["content"] == trusted
                and restored["origins"] == ["external"]
            )
            if not row["repair_verified"]:
                raise RuntimeError("Rebuild invariant failed")
            # Resume at the planner boundary with the repaired slot and untouched remaining slots.
            pristine = suite.load_and_inject_default_environment(
                {slot: restored["content"]}
            )
            _, writes = initial(domain, uid)
            with tempfile.TemporaryDirectory() as temp:
                labels = PersistentLabelStore(Path(temp) / "a.db", Path(temp) / "b.db")
                try:
                    pipeline = Pipeline(c, labels, writes)
                    utility, _ = suite.run_task_with_pipeline(
                        pipeline, task, None, {}, environment=pristine
                    )
                    row["continuation_utility"] = bool(utility)
                finally:
                    labels.close()
        row["status"] = "checked"
    except Exception as exc:
        row.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        store.close()
    row.update(
        seconds=round(time.monotonic() - start, 3),
        calls=c.calls,
        usage=c.usage,
        events=pipeline.events if pipeline else [],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()
    load_env()
    jobs = [
        (d, u, i)
        for d, s in SUITES.items()
        for u in s.user_tasks
        for i in [None, *s.injection_tasks]
        if i is None or int(i.rsplit("_", 1)[1]) not in BENIGN.get(d, set())
    ]
    with ThreadPoolExecutor(args.workers) as pool:
        futures = [pool.submit(evaluate, j, args.output) for j in jobs]
        for f in as_completed(futures):
            f.result()


if __name__ == "__main__":
    main()
