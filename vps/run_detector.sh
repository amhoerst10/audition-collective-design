#!/bin/bash
# Nightly Crawl4AI change detector -- called from root's crontab on the VPS.
set -u
cd /opt/audition-collective
LOG="logs/detector-$(date -u +%F).log"
exec 9>/tmp/ac-detector.lock
flock -n 9 || { echo "$(date -u) already running, skipping" >> "$LOG"; exit 0; }
docker rm -f ac-detector >/dev/null 2>&1
# Whole-run backstop: a normal full run is ~11 min; kill anything past 60.
timeout 60m docker run --rm --name ac-detector --shm-size=1g --memory=4g \
  --env-file /opt/audition-collective/.env \
  -v /opt/audition-collective/detect_url_changes_c4a.py:/app/detect.py:ro \
  ac-crawler python /app/detect.py "$@" >> "$LOG" 2>&1
rc=$?
docker rm -f ac-detector >/dev/null 2>&1
[ $rc -eq 124 ] && echo "$(date -u) KILLED: run exceeded 60 min backstop" >> "$LOG"
echo "exit $rc" >> "$LOG"
find logs -name 'detector-*.log' -mtime +30 -delete
