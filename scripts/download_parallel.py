"""Download remaining official VM ranges with bounded concurrency and resume."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import time
import urllib.request

ROOT = Path("D:/CUA-Lab/cache")
URL = "https://huggingface.co/datasets/xlangai/ubuntu_osworld/resolve/main/Ubuntu-x86.zip"
TOTAL = 12126194516
prefix = ROOT / "Ubuntu-x86.zip.part"
manifest = ROOT / "Ubuntu-x86-ranges.json"
if manifest.exists():
    offset = json.loads(manifest.read_text())["prefix_bytes"]
else:
    offset = prefix.stat().st_size if prefix.exists() else 0
    manifest.write_text(json.dumps({"prefix_bytes": offset, "total": TOTAL, "url": URL}))
if offset != (prefix.stat().st_size if prefix.exists() else 0):
    raise SystemExit("Prefix changed; stop the sequential downloader first")
ranges = [(start, min(TOTAL-1, start+256*1024**2-1)) for start in range(offset, TOTAL, 256*1024**2)]
if shutil.disk_usage(ROOT).free < 2 * (TOTAL-offset) + 5*1024**3:
    raise SystemExit("Insufficient space")

def fetch(pair):
    start, end = pair
    target = ROOT / f"Ubuntu-x86.range-{start}-{end}"
    if target.exists() and target.stat().st_size == end-start+1:
        return target
    for attempt in range(3):
        try:
            request = urllib.request.Request(URL, headers={"Range": f"bytes={start}-{end}"})
            with urllib.request.urlopen(request, timeout=60) as response:
                expected = f"bytes {start}-{end}/{TOTAL}"
                if response.status != 206 or response.headers.get("Content-Range") != expected:
                    raise RuntimeError("Server returned the wrong byte range")
                with target.open("wb") as stream:
                    shutil.copyfileobj(response, stream, 1024**2)
            if target.stat().st_size != end-start+1:
                raise RuntimeError("Partial range")
            print(json.dumps({"range_complete": [start, end]}), flush=True)
            return target
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)

with ThreadPoolExecutor(max_workers=6) as pool:
    parts = list(pool.map(fetch, ranges))
output = ROOT / "Ubuntu-x86.zip.assembling"
with output.open("wb") as out:
    for source in ([prefix] if offset else []) + parts:
        with source.open("rb") as stream:
            shutil.copyfileobj(stream, out, 4*1024**2)
if output.stat().st_size != TOTAL:
    raise SystemExit("Incorrect total size")
output.rename(ROOT / "Ubuntu-x86.zip")
print("Official VM archive download complete; range files preserved until ZIP validation", flush=True)
