# URL Change Detection

**Source**: [`../execution/detect_url_changes.py`](../execution/detect_url_changes.py)
**Directive**: [`../directives/URL_CHANGE_DETECTION.md`](../directives/URL_CHANGE_DETECTION.md) -- the living spec, including the full noise-denylist history. Read that first; this doc covers deployment/ops, the directive covers the detection logic itself.
**Runs**: Hostinger hPanel Cron Job, daily at `0 2 * * *`, directly on the server (see `../architecture/README.md` for why server-side, not local)

## What it does, in one paragraph

For every orchestra URL, fetch the page, strip known noise (see directive), and diff the cleaned text against the last-seen snapshot. A real change creates a row in `url_change_flags` with a full unified diff attached -- not just a boolean "something changed" -- so a human or agent reviewer can tell "new audition posting" from "concert calendar rotated" from "a single character in a footer timestamp changed" at a glance.

## Why full-text diff, not a bare hash

An earlier, unbuilt design nearly hashed page metadata (copyright year, "last updated" stamps) -- explicitly rejected up front because it's known to fail in both directions: false positives from content that changes on its own (timestamps, byline rotation) and false negatives from narrowing the hashed region to avoid those, potentially cropping out exactly where a new audition would appear. Storing full cleaned text and diffing it solves both: noise gets stripped by pattern, and anything not stripped shows up in a reviewable diff regardless of where on the page it appears.

## Deploying to the server (Python 3.6 gotchas)

The Hostinger server's Python is old (3.6.8) and has no `pip` preinstalled. First-time setup:

```bash
curl -s https://bootstrap.pypa.io/pip/3.6/get-pip.py -o /tmp/get-pip.py
python3 /tmp/get-pip.py --user
~/.local/bin/pip3 install --user requests beautifulsoup4 python-dotenv
# mysql-connector-python 8.0.30+ requires Python 3.7+ (uses `from __future__ import annotations`,
# a 3.7+ only feature) -- pin an older version compatible with 3.6:
~/.local/bin/pip3 install --user 'mysql-connector-python==8.0.29'
```

Script + a server-side `.env` (using `DB_HOST=localhost`, same reasoning as the expiry-purge system) get `scp`'d to the server home directory. The cron command:

```
/usr/bin/python3 /home/<user>/detect_url_changes.py >> /home/<user>/url_change_full_run.log 2>&1
```

## Resilience built in (both were needed in production, not theoretical)

- **DNS retry**: each HTTP fetch retries up to 3 times with a pause on any `RequestException`. On top of that, the whole run does up to 3 **sweeps**, retrying only the URLs that failed at the network level each time, with a longer cooldown between sweeps. This was necessary even running from a contributor's home machine at volume; running from the server itself made it nearly unnecessary (0-3 residual network errors per ~400 requests vs. 130+ from home).
- **DB reconnect**: the remote MySQL connection can be dropped mid-run (Hostinger idle-connection timeout, or just flakiness) -- the whole read-then-write unit for each orchestra retries against a freshly reconnected connection rather than trusting one long-lived connection to survive a multi-minute run.
- **Encoding**: `requests` defaults to ISO-8859-1 when a page's `Content-Type` header doesn't declare a charset, mangling UTF-8 into mojibake. Falls back to `apparent_encoding` (real byte detection) whenever the response doesn't declare one explicitly.

## Noise denylist -- confirmed false-positive sources (full history in the directive)

Every one of these was found on a real production run, not anticipated in advance:
- WordPress post "modified" ISO-8601 timestamps and CMS author bylines leaking into body text (day 1 test)
- Gravity Forms' randomizing anti-spam honeypot field label (Atlanta Opera, Quad City Symphony -- first full 408-orchestra scan)
- "Page printed" server-rendered timestamps (Portland Baroque Orchestra)
- Accessibility-accommodation form fragments from a rotating "Desired Concert" dropdown default (North Carolina Symphony)

**Confirmed real-but-irrelevant category** (correctly detected, not noise, but not audition-relevant -- exactly what the human/agent review step exists to filter): rotating "upcoming concerts" calendar widgets. Seen repeatedly (The Orchestra Now/Bard College, Columbus Symphony, Des Moines Metro Opera's "Met Live in HD" schedule, Chicago Philharmonic's event calendar).

## The review workflow (current state: manual)

`url_change_flags.status` starts `unreviewed`. Reviewing means reading `diff_summary` for each row and setting status to `confirmed_real` (with `reviewer_notes` on what to do about it -- often "hand off to `AUDITION_CAPTURE.md` workflow to actually add the listing") or `noise_dismissed` (with notes on why, and ideally a denylist fix if it's a new pattern).

**Not yet built**: an automated trigger that reviews new flags without a human kicking it off. The intended design (per the directive): a second daily scheduled pass, offset ~1 hour after detection, that wakes an agent whose job is exactly the manual process above -- scoped only to that day's flagged rows (typically single digits), not all ~400 orchestras.

## First production run results (2026-09-18, for reference)

Full 408-orchestra baseline: 339 stored cleanly from a contributor's home machine (69 errors, mostly legitimate bot-blocking/dead-link HTTP statuses, not real gaps), then completed to 408 once moved server-side. First 3 days of live flags: 16 total, 14 noise/irrelevant (2 new denylist patterns fixed as a direct result), 1 self-resolving (an orchestra's site removed a same-day-past audition announcement -- DB already correctly reflected this), and **1 genuine gap found**: LA Chamber Orchestra had 2 open positions live on their site that weren't yet in the database.
