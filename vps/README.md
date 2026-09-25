# VPS: Crawl4AI change detector

The nightly URL change detector runs on a Hostinger **KVM 2 VPS** (`srv997890.hstgr.cloud`, 72.60.123.209, Ubuntu 24.04, 2 vCPU / 8 GB). It is separate from the shared web hosting that serves the WordPress site. The VPS also runs an n8n install in its own containers; the detector doesn't touch it.

Why a VPS: the detector needs a real headless browser (Chromium, via Crawl4AI). The shared hosting server's Python 3.6 can't run that, and a contributor's home machine is unreliable (router DNS drops, and it isn't always on). See `../automation-design/url-change-detection-system.md`.

## Files

| File | Where it goes on the VPS |
|---|---|
| `Dockerfile` | `/opt/audition-collective/Dockerfile` -- builds `ac-crawler` (official Crawl4AI image + MySQL connector) |
| `run_detector.sh` | `/opt/audition-collective/run_detector.sh` -- cron wrapper: lock file (no overlapping runs), one-shot container, dated log, 30-day log cleanup |
| `crontab.txt` | root's crontab |
| `../execution/detect_url_changes_c4a.py` | `/opt/audition-collective/detect_url_changes_c4a.py` -- mounted read-only into the container |
| `.env` (not in repo) | `/opt/audition-collective/.env`, mode 600 -- ONLY `DB_HOST` (public IP), `DB_USER`, `DB_PASSWORD`, `DB_NAME`. No SSH or other keys on this box. |

## Rebuild from scratch

```bash
mkdir -p /opt/audition-collective/logs && cd /opt/audition-collective
# copy Dockerfile, run_detector.sh, detect_url_changes_c4a.py here; create .env
chmod 600 .env && chmod +x run_detector.sh
docker build -t ac-crawler .
./run_detector.sh --limit 5          # smoke test; check logs/detector-*.log
(crontab -l 2>/dev/null; echo "0 7 * * * /opt/audition-collective/run_detector.sh") | crontab -
```

Script edits: copy the new `detect_url_changes_c4a.py` over; the next run picks it up (no rebuild needed). Only rebuild the image to change dependencies or upgrade Crawl4AI. **If you change the noise rules or cleaning logic, `TRUNCATE url_change_snapshots_c4a` and run once manually to re-baseline** (see the directive's full-re-baseline rule).

## Gotchas found during setup

- **SSH from Windows**: the local key is passphrase-protected, so the Git-Bash `ssh` fails non-interactively. Use Windows' own `C:\Windows\System32\OpenSSH\ssh.exe`, which uses the Windows ssh-agent where the key is already unlocked.
- **hPanel "SSH keys" didn't take effect by itself** on this n8n-template VPS; the key had to be appended to `/root/.ssh/authorized_keys` from the hPanel Web console. When appending, use `printf '\n<key>\n' >>` -- a plain `echo >>` glued the new key onto the end of an existing line that lacked a trailing newline.
- **Crawl4AI's built-in API server** (the long-running `unclecode/crawl4ai` container) binds to its own loopback in v0.9.x, so a Docker port mapping can't reach it. We don't use the API server at all: the detector runs the Crawl4AI Python library directly in a one-shot container per night.
- **Remote MySQL**: the VPS connects to the orchestras DB over the public IP (it isn't on the same machine as the database, so `localhost` doesn't apply here, unlike the scripts that run on the shared hosting server).
- **500 remote connections per hour cap** (MySQL error 1226, `max_connections_per_hour`). Counted per user@host, so WordPress (via `localhost`) isn't affected, but the VPS and any laptop queries share the remote budget. An early version opened a connection per DB call, hit the cap mid-run, and lost ~135 results. The detector now reuses a single connection. Don't reintroduce connection-per-call.
- **Phoenix Symphony hung the browser for 2+ hours** on the first full run. Crawl4AI's `page_timeout` didn't stop it, hence the 120-second per-site `asyncio.wait_for` cap in the script and the 60-minute whole-run `timeout` in `run_detector.sh`.
- **Launch manual runs detached** (`setsid nohup ./run_detector.sh &`). A run tied to an SSH session dies when the connection drops, and the home router drops connections regularly.
