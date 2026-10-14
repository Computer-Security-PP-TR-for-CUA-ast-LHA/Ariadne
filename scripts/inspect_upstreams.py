"""Capture small public upstream revision metadata; does not install or execute it."""
import json
from pathlib import Path
import urllib.request


def get(url):
    request = urllib.request.Request(url, headers={"User-Agent": "cua-research-metadata"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    rows = []
    for name in ("TanqiuJiang/AgentLAB", "OSU-NLP-Group/RedTeamCUA"):
        root = "https://api.github.com/repos/" + name
        metadata = get(root)
        commit = get(root + "/commits/" + metadata["default_branch"])
        rows.append({"repository": name, "url": metadata["html_url"],
                     "default_branch": metadata["default_branch"], "commit": commit["sha"],
                     "commit_date": commit["commit"]["committer"]["date"],
                     "github_license_detection": (metadata.get("license") or {}).get("spdx_id"),
                     "note": "Revision metadata only; not cloned, installed or reproduced."})
    target = Path(__file__).resolve().parents[1] / "docs" / "upstream-revisions.json"
    target.write_text(json.dumps({"checked_on": "2026-10-14", "upstreams": rows}, indent=2) + "\n",
                      encoding="utf-8")
    print(target.name)
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
