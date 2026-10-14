#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -x .venv-wsl/bin/python ]]; then
    if command -v uv >/dev/null 2>&1; then
        uv venv --offline --python 3.13 .venv-wsl
    else
        python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
        python3 -m venv --without-pip .venv-wsl
    fi
fi
.venv-wsl/bin/python -c 'import pathlib,site; pathlib.Path(site.getsitepackages()[0], "cua_guard_local.pth").write_text(str(pathlib.Path("src").resolve()) + "\n", encoding="utf-8")'
bash scripts/check.sh
