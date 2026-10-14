"""Read-only GitHub access check using the normal Git credential helper.

No credential values are printed or persisted. Interactive login is disabled.
"""
import json
import os
import subprocess
import urllib.error
import urllib.request

ORG = "Computer-Security-PP-TR-for-CUA-ast-LHA"


def main():
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="Never")
    try:
        result = subprocess.run(["git", "credential", "fill"],
                                input="protocol=https\nhost=github.com\n\n",
                                text=True, capture_output=True, env=env, timeout=20)
    except subprocess.TimeoutExpired:
        print(json.dumps({"authenticated": False, "reason": "credential_helper_timeout"}))
        return
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    token = fields.get("password")
    if result.returncode or not token:
        print(json.dumps({"authenticated": False, "reason": "no_noninteractive_git_credential"}))
        return

    def get(path):
        request = urllib.request.Request("https://api.github.com" + path, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json", "User-Agent": "cua-project-setup"})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    try:
        user = get("/user")
        membership = get("/user/memberships/orgs/" + ORG)
        print(json.dumps({"authenticated": True, "login": user["login"],
                          "org": ORG, "membership": membership.get("state"),
                          "role": membership.get("role")}))
    except urllib.error.HTTPError as exc:
        print(json.dumps({"authenticated": False, "http_status": exc.code,
                          "reason": "credential_or_org_access_unverified"}))
    except urllib.error.URLError:
        print(json.dumps({"authenticated": False, "reason": "network_unavailable"}))


if __name__ == "__main__":
    main()
