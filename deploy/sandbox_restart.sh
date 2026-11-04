#!/usr/bin/env bash
# Recover the scheduler after a host/sandbox reboot. The container is RECREATED (not restarted) so it picks up the
# current network/proxy settings of this boot; stale settings caused "connection refused" on 2026-11-04.
set -euo pipefail
R="${EVOX_ROOT:-/home/user/evolution-x}"
if ! docker info >/dev/null 2>&1; then
  (nohup dockerd >/tmp/dockerd.log 2>&1 &)
  for _ in $(seq 1 40); do docker info >/dev/null 2>&1 && break; sleep 1; done
fi
docker rm -f evox-scheduler >/dev/null 2>&1 || true
docker run -d --name evox-scheduler --network host --restart unless-stopped --stop-timeout 90 \
  -v "$R:$R" -v /root/.ccr:/root/.ccr:ro -w /tmp -e EVOX_ROOT="$R" -e HTTPS_PROXY -e SSL_CERT_FILE \
  -e PYTHONUNBUFFERED=1 python:3.13-slim "$R/.venv/bin/evox" ops daemon --interval 60
