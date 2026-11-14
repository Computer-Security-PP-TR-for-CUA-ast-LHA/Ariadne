#!/usr/bin/env bash
set -euo pipefail
if [[ "${WSL_DISTRO_NAME:-}" != "AriadneLab" ]]; then
  echo 'Use the dedicated AriadneLab WSL distribution' >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  nohup dockerd > /var/log/ariadne-docker.log 2>&1 < /dev/null &
  for attempt in $(seq 1 30); do
    docker info >/dev/null 2>&1 && break
    sleep 1
  done
fi
image='am1n3e/webarena-verified-reddit@sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46'
digest="${image#*@}"
if docker image inspect "$digest" >/dev/null 2>&1; then
  image="$digest"
else
  docker pull "$image"
fi
if ! docker container inspect ariadne-forum >/dev/null 2>&1; then
  docker run -d --name ariadne-forum --label org.ariadne.lab=true \
    --restart unless-stopped -p 127.0.0.1:9999:80 "$image"
else
  expected=$(docker image inspect "$image" --format '{{.Id}}')
  actual=$(docker inspect ariadne-forum --format '{{.Image}}')
  [[ "$expected" == "$actual" ]] || { echo 'Existing container has a different image'; exit 1; }
  docker start ariadne-forum
fi
docker exec ariadne-forum env-ctrl init --base-url http://127.0.0.1:9999/
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:9999/ -o /tmp/ariadne-forum.html; then
    echo 'Forum HTTP health check passed at http://localhost:9999'
    exit 0
  fi
  sleep 2
done
echo 'Forum not healthy; inspect docker logs ariadne-forum' >&2
exit 1
