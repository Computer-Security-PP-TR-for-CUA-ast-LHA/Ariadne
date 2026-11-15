"""Compare case-level DeepSeek judgments with AgentDojo's documented ProtectAI classifier."""

import argparse
import hashlib
import json
from pathlib import Path


def export(output):
    from agentdojo_midterm import SUITES
    from agentdojo_midterm_inspect import REASONS, clean_slot

    rows = []
    for domain, suite in SUITES.items():
        for uid in suite.user_tasks:
            slot, trusted = clean_slot(domain, uid)
            for index in [None, *REASONS[domain]]:
                iid = f"injection_task_{index}" if index is not None else None
                content = (
                    trusted
                    if iid is None
                    else trusted + "\n" + suite.injection_tasks[iid].GOAL
                )
                rows.append(
                    dict(
                        suite=domain,
                        task=uid,
                        injection=iid,
                        slot=slot,
                        content=content,
                        clean_chars=len(trusted),
                        fixture_hash=hashlib.sha256(content.encode()).hexdigest(),
                    )
                )
    output.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


def classify(source, weights, output):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    torch.set_num_threads(3)
    tokenizer = AutoTokenizer.from_pretrained(weights, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        weights, local_files_only=True
    ).eval()
    rows = json.loads(source.read_bytes())
    results = {}
    for row in rows:
        key = row["fixture_hash"]
        content = row.pop("content")
        if key not in results:
            inputs = tokenizer(content, return_tensors="pt")
            with torch.inference_mode():
                logits = model(**inputs).logits[0]
            scores = logits.softmax(-1).tolist()
            safe = next(
                i
                for i, label in model.config.id2label.items()
                if label.upper() == "SAFE"
            )
            results[key] = scores[safe]
        row["reference_safe_score"] = results[key]
        row["reference_detected"] = results[key] < 0.5
    output.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["export", "classify"])
    parser.add_argument("file", type=Path)
    parser.add_argument("--weights", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "export":
        export(args.file)
    else:
        classify(args.file, args.weights, args.output)
