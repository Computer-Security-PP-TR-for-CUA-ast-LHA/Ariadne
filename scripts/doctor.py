"""Read-only readiness checks. Never emits API keys or credential values."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from cua_guard.model import load_env

load_env()
report = {
    "python": sys.version.split()[0],
    "model": os.environ.get("MODEL_ID", "deepseek-flash"),
    "model_base_url": os.environ.get("MODEL_BASE_URL", "https://api.deepseek.com"),
    "model_key_present": bool(os.environ.get("MODEL_API_KEY")),
    "max_calls": os.environ.get("MODEL_MAX_CALLS", "20"),
    "upstreams": {name: Path("D:/CUA-Lab/upstream", name).is_dir()
                  for name in ("AgentLAB", "RedTeamCUA")},
    "vm_archive_complete": Path("D:/CUA-Lab/cache/Ubuntu-x86.zip").exists(),
    "modules": {name: importlib.util.find_spec(name) is not None
                for name in ("requests", "gymnasium", "sotopia", "torch")},
    "git": shutil.which("git") is not None,
}
print(json.dumps(report, indent=2))
