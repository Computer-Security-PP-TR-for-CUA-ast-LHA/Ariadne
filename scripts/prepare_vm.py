"""Validate/extract the official OSWorld ZIP to a new dedicated VM directory."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

p = argparse.ArgumentParser()
p.add_argument("archive", type=Path)
p.add_argument("destination", type=Path)
a = p.parse_args()
destination = a.destination.resolve()
if destination.exists() and any(destination.iterdir()):
    raise SystemExit("Destination must be new or empty; existing VM is never overwritten")
with zipfile.ZipFile(a.archive) as archive:
    size = sum(info.file_size for info in archive.infolist())
    destination.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(destination).free < size + 5 * 1024**3:
        raise SystemExit("Not enough disk space to extract VM")
    for info in archive.infolist():
        path = PurePosixPath(info.filename.replace("\\", "/"))
        mode = info.external_attr >> 16
        if path.is_absolute() or ".." in path.parts or any(":" in part for part in path.parts) or stat.S_ISLNK(mode):
            raise SystemExit("Unsafe archive member")
        target = (destination / str(path)).resolve()
        if not target.is_relative_to(destination):
            raise SystemExit("Archive escapes destination")
    # ZipFile verifies CRC on each member during extraction.
    archive.extractall(destination)
vmx = list(destination.rglob("*.vmx"))
if len(vmx) != 1:
    raise SystemExit("Expected exactly one VMware configuration")
with a.archive.open("rb") as source:
    checksum = hashlib.file_digest(source, "sha256").hexdigest()
report = {"archive_sha256": checksum, "expanded_bytes": size, "vmx": str(vmx[0]),
          "status": "extracted_only_not_booted"}
(destination / "ariadne-vm.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps(report))
