"""Resumable official asset download; urllib honors Windows proxy settings."""
import argparse
import json
from pathlib import Path
import shutil
import urllib.request

p = argparse.ArgumentParser()
p.add_argument("url")
p.add_argument("output", type=Path)
a = p.parse_args()
a.output.parent.mkdir(parents=True, exist_ok=True)
part = a.output.with_suffix(a.output.suffix + ".part")
offset = part.stat().st_size if part.exists() else 0
req = urllib.request.Request(a.url, headers={"Range": f"bytes={offset}-"} if offset else {})
with urllib.request.urlopen(req, timeout=60) as response:
    if offset and response.status != 206:
        raise RuntimeError("Server did not honor resume; partial file preserved")
    remaining = int(response.headers.get("Content-Length", 0))
    if shutil.disk_usage(a.output.parent).free < remaining + 5 * 1024**3:
        raise RuntimeError("Insufficient disk space")
    count = offset
    with part.open("ab" if offset else "wb") as target:
        while chunk := response.read(4 * 1024**2):
            target.write(chunk)
            count += len(chunk)
            if count // (256 * 1024**2) != (count-len(chunk)) // (256 * 1024**2):
                print(json.dumps({"bytes": count, "total": offset + remaining}), flush=True)
    if remaining and count != offset + remaining:
        raise RuntimeError("Incomplete asset; resume on next run")
part.rename(a.output)
print(json.dumps({"complete": str(a.output), "bytes": count}), flush=True)
