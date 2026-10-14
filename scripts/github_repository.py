"""Create the authorized private Ariadne repository, or inspect remote/CI state.

Uses Git's credential helper in memory. Never prints/persists credential values.
Creation refuses to change an existing repository. Git push is a separate step.
"""
import argparse
import json
import os
import subprocess
import urllib.error
import urllib.request

ORG = "Computer-Security-PP-TR-for-CUA-ast-LHA"
NAME = "Ariadne"
BASE = f"/repos/{ORG}/{NAME}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("create", "status"))
    args = parser.parse_args()
    result = subprocess.run(
        ["git", "credential", "fill"], input="protocol=https\nhost=github.com\n\n",
        text=True, capture_output=True, timeout=20,
        env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never"))
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    token = fields.get("password")
    if result.returncode or not token:
        raise SystemExit("GitHub credential unavailable")

    def api(path, data=None):
        request = urllib.request.Request(
            "https://api.github.com" + path,
            data=None if data is None else json.dumps(data).encode(),
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     "Content-Type": "application/json", "User-Agent": "ariadne-project-setup"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    if args.mode == "create":
        try:
            api(BASE)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise SystemExit(f"Repository preflight HTTP {exc.code}") from None
        else:
            raise SystemExit("Repository already exists; inspect it before changing anything")
        repo = api(f"/orgs/{ORG}/repos", {
            "name": NAME, "private": True, "auto_init": False,
            "description": "Persistent provenance and targeted repair for computer-use agents",
            "has_issues": True, "has_projects": True, "has_wiki": False})
        print(json.dumps({k: repo[k] for k in ("full_name", "html_url", "private", "clone_url")}, indent=2))
        return

    repo = api(BASE)
    print(json.dumps({k: repo[k] for k in ("full_name", "html_url", "private", "default_branch")}, indent=2))
    try:
        branch = api(BASE + "/branches/" + repo["default_branch"])
        print(json.dumps({"remote_sha": branch["commit"]["sha"]}))
    except urllib.error.HTTPError as exc:
        print(json.dumps({"branch_status": exc.code}))
    runs = api(BASE + "/actions/runs?per_page=3")
    for run in runs["workflow_runs"]:
        print(json.dumps({k: run.get(k) for k in
                          ("id", "name", "head_sha", "status", "conclusion", "html_url")}, indent=2))
        jobs = api(BASE + f"/actions/runs/{run['id']}/jobs")
        for job in jobs["jobs"]:
            print(json.dumps({"job": job["name"], "status": job["status"],
                              "conclusion": job["conclusion"], "html_url": job["html_url"],
                              "failed_steps": [s["name"] for s in job.get("steps", [])
                                               if s.get("conclusion") == "failure"]}))


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"GitHub API HTTP {exc.code}") from None
