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

## The review workflow (current state: manual, with a mandatory independent QA step before any DB write)

`url_change_flags.status` starts `unreviewed`. Reviewing means reading `diff_summary` for each row and setting status to `confirmed_real` (with `reviewer_notes` on what to do about it) or `noise_dismissed` (with notes on why, and ideally a denylist fix if it's a new pattern).

**A `diff_summary` read is a hypothesis, not a verified fact -- it must be independently re-checked against the live page before writing anything to `auditions`.** This was learned the hard way on 2026-09-23: a diff-based read correctly identified that Erie Philharmonic's page had changed, but the initial interpretation (positions changed but roughly similar) undersold it -- an independent live-page re-check (via a separate agent given only the URLs, not the prior diff analysis) found the page had actually rotated to 3 completely different positions with zero overlap with either the old DB state or the initial read. Same pattern at Nashville Civic Orchestra: the diff showed "a large change," but only a fresh independent read revealed the entire principal/section-leader audition track had closed, replaced by unpaid rolling section auditions -- a categorically different situation than "some fields changed."

**Practical rule**: for every flag marked `confirmed_real` that will result in an `auditions` table write, re-fetch the live page independently (a separate agent invocation given only the URL, explicitly instructed not to trust the prior diff/summary) before writing anything. Cheap insurance against a diff-reader's own interpretation bias, and it caught a real, consequential error the diff-only read would have gotten wrong.

**Not yet built**: an automated trigger that reviews new flags without a human kicking it off. The intended design (per the directive): a second daily scheduled pass, offset ~1 hour after detection, that wakes an agent whose job is the review-then-independently-verify process above -- scoped only to that day's flagged rows (typically single digits), not all ~400 orchestras.

## Production history

**2026-09-18, first run**: Full 408-orchestra baseline: 339 stored cleanly from a contributor's home machine (69 errors, mostly legitimate bot-blocking/dead-link HTTP statuses, not real gaps), then completed to 408 once moved server-side. First 3 days of live flags: 16 total, 14 noise/irrelevant (2 new denylist patterns fixed as a direct result), 1 self-resolving, and 1 genuine gap found (LA Chamber Orchestra).

**2026-09-22/23, a self-inflicted regression**: a noise-pattern fix from the prior review session was too broad (matched a single common word alone) and, combined with only a partial re-baseline, produced ~40-60 false "content changed" flags across unrelated orchestras over two nights. Caught only because the project owner asked for a routine status check-in -- nothing in the system alerted on its own. Fixed (tightened regex, full re-baseline, and the "any noise-pattern change requires a full re-baseline" rule added to the directive). Buried in that same noisy batch were 6 genuine findings, later independently QA-verified and used to correct the database -- see the incident above for what that verification step caught that a diff-only read would have missed.

## Honest accuracy assessment: automated diff detection vs. manual full re-audit

Neither is "the accurate one" in isolation -- they catch different failure modes:

- **Automated diff detection's real value**: continuous, cheap, daily coverage of all ~400 sites -- something a manual state-by-state re-audit cannot realistically do at that frequency. It reliably tells you *something changed*, and has caught real gaps (LA Chamber Orchestra, Erie Philharmonic's full position rotation, Nashville Civic Orchestra's structural closure) that would otherwise have sat stale indefinitely between manual audit passes.
- **Automated diff detection's real failure modes, both observed in production, not hypothetical**: (1) it can be wrong about what changed being *noise vs. real* (the Gravity Forms honeypot, the "Name" regression), and a bad noise-pattern fix can silently degrade accuracy across the whole dataset until someone notices; (2) even when a diff is correctly flagged as real, the *interpretation* of what it means can be wrong without independent verification (Erie, Nashville).
- **Manual full re-audits (the original state-by-state 3-agent process) are higher-confidence per orchestra** -- a human-directed close read of one page beats a heuristic diff every time -- **but don't scale to daily monitoring of 400+ sites.** They're the right tool for periodic deep verification, not continuous change detection.

**Recommendation**: keep the hybrid. Automated detection stays the daily first-pass filter; every `confirmed_real` flag gets an independent live re-check before any DB write (now a hard rule, not optional); and the original manual state-by-state audit process should still run periodically (e.g. a rotating subset each month) as a backstop against the automated system's blind spot -- anything that's been wrong since initial capture and simply never changes again will never trigger a diff, no matter how well the detection logic works.
