#!/usr/bin/env bash
# Host-side ticks until today's research slot is terminal (the research sandbox only works on the host).
cd "${EVOX_ROOT:-/home/user/evolution-x}"
D=$(date -u +%F)
for i in $(seq 1 180); do
  st=$(.venv/bin/python -c "import sqlite3;r=sqlite3.connect('artifacts/ops/ops.db').execute(\"select status from runs where job='research_army' and slot=?\",('$D',)).fetchone();print(r[0] if r else 'none')")
  case "$st" in succeeded|skipped|failed) echo "done: $st"; exit 0;; esac
  (cd /tmp && "${EVOX_ROOT:-/home/user/evolution-x}/.venv/bin/evox" ops tick >/dev/null 2>&1)
  sleep 30
done
