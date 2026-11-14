"""Load pinned research artifacts without reimplementing their algorithms.

Third-party checkouts live outside this repository. This module verifies their
identity before importing the author's code; it is integration glue, not a
replacement provenance, detector, or repair implementation.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


class UpstreamRegistry:
    def __init__(self, root=None, manifest=None):
        self.root = Path(root or os.environ.get("ARIADNE_UPSTREAM_ROOT", "D:/CUA-Lab/upstream")).resolve()
        manifest = Path(manifest or Path(__file__).resolve().parents[2] / "docs/upstream-reuse-lock.json")
        self.lock = json.loads(manifest.read_text(encoding="utf-8"))
        self.sources = {item["name"]: item for item in self.lock["sources"]}

    def verify(self, name):
        source = self.sources[name]
        path = self.root / name
        sha = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        if sha != source["commit"]:
            raise RuntimeError(f"{name}: revision differs from the reviewed lock")
        changed = subprocess.check_output(
            ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"], text=True
        ).strip()
        if changed:
            raise RuntimeError(f"{name}: tracked source files have changed")
        return path

    def openappa(self, tools_root=None):
        release = self.lock["openappa_binary"]
        tools = Path(tools_root or self.root.parent / "tools")
        binary = tools / release["relative_path"]
        if hashlib.sha256(binary.read_bytes()).hexdigest() != release["sha256"]:
            raise RuntimeError("OpenAPPA executable differs from the verified release")
        return binary

    def tma_authority_modules(self):
        """Return the actual author-provided scope gate and recovery catalog.

        The catalog uses a top-level import in the original artifact. Refuse an
        existing unrelated module instead of silently mixing implementations.
        """
        root = self.verify("mem-inv-bench") / "code"
        loaded = []
        for name in ("scoped_authorization", "recovery_catalog"):
            path = root / (name + ".py")
            module = sys.modules.get(name)
            if module is not None:
                if Path(module.__file__).resolve() != path.resolve():
                    raise RuntimeError(f"Conflicting module: {name}")
            else:
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                try:
                    spec.loader.exec_module(module)
                except BaseException:
                    sys.modules.pop(name, None)
                    raise
            loaded.append(module)
        return tuple(loaded)
