"""Evaluate the production semantic detector on RTC fixture text without executing actions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

import pdfplumber
from cua_guard.model import DeepSeekClient, load_env
from cua_guard.semantic import SemanticDefense


@lru_cache(maxsize=384)
def pdf_text(path):
    with pdfplumber.open(path) as document:
        text = "\n".join(page.extract_text() or "" for page in document.pages)
    if not text.strip():
        raise ValueError("Empty PDF text")
    return text


def inspect_case(item):
    row, record, root = item
    try:
        params = record["adversary_config"][0]["parameters"]
        domain = row["platform"]
        if domain == "owncloud":
            content = pdf_text(root / params["local_file_path"])
        elif domain == "reddit":
            content = params["new_content"]
        else:
            content = params["scenarios_json_data"]["Mike Chen"]["strategy_hint"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Missing fixture text")
        row["chars"] = len(content)
        row["sha256"] = hashlib.sha256(content.encode()).hexdigest()
        client = DeepSeekClient(os.environ["MODEL_API_KEY"], model="deepseek-flash", max_calls=2)
        defense = SemanticDefense(None, client)
        start = time.monotonic()
        for attempt in range(2):
            try:
                result = defense.inspect(record["instruction"], content)
                row.update(verdict=result["verdict"], evidence_spans=[
                    [content.index(e),len(e)] for e in result["evidence"]])
                break
            except Exception as exc:
                row.setdefault("errors", []).append(str(exc))
                if attempt or not any(s in str(exc) for s in ("429","transport","502","503","504")):
                    break
                time.sleep(2)
        row.update(seconds=round(time.monotonic()-start,3),calls=client.calls, usage=client.usage)
    except Exception as exc:
        row.setdefault("errors", []).append(str(exc))
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("upstream",type=Path)
    ap.add_argument("output",type=Path)
    args=ap.parse_args()
    rev=subprocess.check_output(["git","-C",str(args.upstream),"rev-parse","HEAD"],text=True).strip()
    if rev != "a05b8bd04629e19a9a06bf04f8e0c5b53549d16c":
        raise ValueError("Unexpected upstream revision")
    load_env()
    folder=args.upstream/"evaluation_examples"
    items=[]
    with zipfile.ZipFile(folder/"RedTeamCUA_configs.zip") as archive:
        for domain, ids in json.loads((folder/"test_all.json").read_bytes()).items():
            for case in ids:
                rec=json.loads(archive.read(f"examples/{domain}/{case}.json"))
                if rec["id"] != case or rec["platform"] != domain:
                    raise ValueError(case)
                row=dict(case=case,platform=domain,revision=rev,model="deepseek-flash",
                         **rec["meta_data"])
                items.append((row,rec,args.upstream))
    with args.output.open("x",encoding="utf-8") as stream, ThreadPoolExecutor(max_workers=12) as pool:
        for row in pool.map(inspect_case,items):
            stream.write(json.dumps(row)+"\n")
            stream.flush()

if __name__=="__main__":
    main()
