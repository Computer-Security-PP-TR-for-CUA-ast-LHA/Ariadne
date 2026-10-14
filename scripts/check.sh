#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
task_python=python3
if [[ -x .venv-wsl/bin/python ]]; then task_python=.venv-wsl/bin/python; fi
"$task_python" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
"$task_python" -m unittest discover -s tests -v
"$task_python" -m cua_guard.demo
