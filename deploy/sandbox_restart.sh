#!/usr/bin/env bash
# Recover the scheduler after a host/sandbox reboot. The container is RECREATED (not restarted) so it picks up the
# current network/proxy settings of this boot; optional research is skipped in the container (its sandbox needs
# host namespaces) and run by host-side ticks; stale settings caused "connection refused" on 2026-11-04.
set -euo pipefail
R="${EVOX_ROOT:-/home/user/evolution-x}"
for attempt in 1 2 3; do  # containerd can time out on a cold boot: retry the daemon
  docker info >/dev/null 2>&1 && break
  pgrep -x dockerd >/dev/null || (nohup dockerd >>/tmp/dockerd.log 2>&1 &)
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done
done
docker info >/dev/null
docker rm -f evox-scheduler >/dev/null 2>&1 || true
docker run -d --name evox-scheduler --network host --restart unless-stopped --stop-timeout 90 \
  -v "$R:$R" -v /root/.ccr:/root/.ccr:ro -w /tmp -e EVOX_ROOT="$R" -e HTTPS_PROXY -e SSL_CERT_FILE \
  -e PYTHONUNBUFFERED=1 -e EVOX_SKIP_JOBS=research_army python:3.13-slim "$R/.venv/bin/evox" ops daemon --interval 60
