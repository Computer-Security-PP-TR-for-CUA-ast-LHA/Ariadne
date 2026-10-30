#!/usr/bin/env bash
set -euo pipefail
# Run only in the dedicated AriadneLab WSL distribution on D:.
if [[ "${WSL_DISTRO_NAME:-}" != "AriadneLab" ]]; then
  echo 'Refusing to modify a distribution other than AriadneLab' >&2
  exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends docker.io ca-certificates curl python3
if ! docker info >/dev/null 2>&1; then
  nohup dockerd > /var/log/ariadne-docker.log 2>&1 < /dev/null &
  for attempt in $(seq 1 30); do
    docker info >/dev/null 2>&1 && break
    sleep 1
  done
fi
docker info --format '{{.ServerVersion}}'
