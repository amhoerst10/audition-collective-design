#!/bin/bash
# Nightly Crawl4AI change detector -- called from root's crontab on the VPS.
set -u
cd /opt/audition-collective
LOG="logs/detector-$(date -u +%F).log"
exec 9>/tmp/ac-detector.lock
flock -n 9 || { echo "$(date -u) already running, skipping" >> "$LOG"; exit 0; }
docker rm -f ac-detector >/dev/null 2>&1
# Hostinger's /etc/cron.d/docker-image-prune deletes unused images >24h old,
# which wiped this image on 2026-09-26. The stopped ac-crawler-keep container
# pins it; rebuild here as a backstop if it's missing anyway.
if ! docker image inspect ac-crawler >/dev/null 2>&1; then
  echo "$(date -u) ac-crawler image missing -- rebuilding" >> "$LOG"
  docker build -q -t ac-crawler /opt/audition-collective >> "$LOG" 2>&1
  docker rm -f ac-crawler-keep >/dev/null 2>&1
  docker create --name ac-crawler-keep ac-crawler true >/dev/null 2>&1
fi
# Whole-run backstop: a normal (polite, concurrency 2) run is ~30 min; kill anything past 90.
timeout 90m docker run --rm --name ac-detector --shm-size=1g --memory=4g \
  --env-file /opt/audition-collective/.env \
  -v /opt/audition-collective/detect_url_changes_c4a.py:/app/detect.py:ro \
  ac-crawler python /app/detect.py "$@" >> "$LOG" 2>&1
rc=$?
docker rm -f ac-detector >/dev/null 2>&1
# Data-integrity pass: flags listings whose dates/fields look like capture
# errors (prelim without final, missing deadline near the audition, dates out
# of order, orchestras with no rows, ...) into the manual-check queue.
echo "--- integrity check ---" >> "$LOG"
timeout 10m docker run --rm --name ac-integrity \
  --env-file /opt/audition-collective/.env \
  -v /opt/audition-collective/check_data_integrity.py:/app/integrity.py:ro \
  ac-crawler python /app/integrity.py >> "$LOG" 2>&1
# Job-board cross-check: musicalchairs.info US postings vs our listings.
# Catches openings on sites that block us and ones we missed elsewhere.
echo "--- job-board check ---" >> "$LOG"
timeout 20m docker run --rm --name ac-jobboard --shm-size=1g \
  --env-file /opt/audition-collective/.env \
  -v /opt/audition-collective/check_job_boards.py:/app/jobboards.py:ro \
  ac-crawler python /app/jobboards.py >> "$LOG" 2>&1
[ $rc -eq 124 ] && echo "$(date -u) KILLED: run exceeded 90 min backstop" >> "$LOG"
echo "exit $rc" >> "$LOG"
find logs -name 'detector-*.log' -mtime +30 -delete
