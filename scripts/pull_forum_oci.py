"""Fetch the pinned public forum image through Windows' configured proxy.

Creates an OCI archive for docker load in the dedicated WSL distribution.
Every registry object is SHA256 verified. No Docker credentials are read.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import tarfile
import urllib.request

REPO = "am1n3e/webarena-verified-reddit"
DIGEST = "sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46"
ROOT = Path("D:/CUA-Lab/cache/forum-oci")
ROOT.mkdir(parents=True, exist_ok=True)
token_url = "https://auth.docker.io/token?service=registry.docker.io&scope=repository:" + REPO + ":pull"
with urllib.request.urlopen(token_url, timeout=30) as response:
    token = json.load(response)["token"]
headers = {"Authorization": "Bearer " + token,
           "Accept": "application/vnd.docker.distribution.manifest.v2+json, application/vnd.oci.image.manifest.v1+json"}
url = "https://registry-1.docker.io/v2/" + REPO
with urllib.request.urlopen(urllib.request.Request(url + "/manifests/" + DIGEST, headers=headers), timeout=60) as response:
    raw_manifest = response.read()
if "sha256:" + hashlib.sha256(raw_manifest).hexdigest() != DIGEST:
    raise RuntimeError("Manifest checksum mismatch")
manifest = json.loads(raw_manifest)

def blob(item):
    expected = item["digest"].removeprefix("sha256:")
    target = ROOT / expected
    if target.exists():
        with target.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() == expected:
                return target
    temp = target.with_suffix(".part")
    request = urllib.request.Request(url + "/blobs/" + item["digest"], headers=headers)
    checksum = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=90) as response, temp.open("wb") as output:
        while chunk := response.read(1024**2):
            output.write(chunk)
            checksum.update(chunk)
    if checksum.hexdigest() != expected or temp.stat().st_size != item["size"]:
        raise RuntimeError("Layer checksum/size mismatch")
    temp.replace(target)
    print(json.dumps({"verified_blob": expected, "bytes": item["size"]}), flush=True)
    return target

with ThreadPoolExecutor(max_workers=4) as pool:
    paths = list(pool.map(blob, [manifest["config"], *manifest["layers"]]))
index = {"schemaVersion": 2, "manifests": [{"mediaType": manifest["mediaType"],
         "digest": DIGEST, "size": len(raw_manifest), "annotations": {
             "org.opencontainers.image.ref.name": "ariadne-forum:verified"}}]}
archive = ROOT.parent / "ariadne-forum-oci.tar"
with tarfile.open(archive, "w") as out:
    def add(name, data):
        info = tarfile.TarInfo(name)
        info.size = len(data)
        out.addfile(info, io.BytesIO(data))
    add("oci-layout", b'{"imageLayoutVersion":"1.0.0"}')
    add("index.json", json.dumps(index).encode())
    add("blobs/sha256/" + DIGEST.split(":")[1], raw_manifest)
    for path in dict.fromkeys(paths):
        out.add(path, arcname="blobs/sha256/" + path.name, recursive=False)
print(json.dumps({"archive": str(archive), "digest": DIGEST}), flush=True)
