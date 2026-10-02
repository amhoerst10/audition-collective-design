"""
Same-day alert triage: tags nightly change flags whose ADDED lines look like a
new audition posting (an instrument/position word near a date or deadline) so
a daily review picks them up within hours instead of waiting in the queue.

Why: on 2026-09-30 the BSO posted Third Horn and Section Viola. The detector
flagged it overnight, but the flag sat unreviewed among ~200 noise flags until
the owner noticed the opening himself. Most flags are noise (ticket banners,
countdowns, cookie widgets), so a cheap keyword screen separates the few that
matter.

What it does: for c4a flags from the last 36 h with status 'unreviewed' and no
failure_reason, it sets failure_reason='likely_new_audition' when an added
line (diff '+' line, not also present as a '-' line) matches an instrument or
position word AND, on the same line or within the next 3 added lines, a date,
deadline or audition word. Job-board mismatches (already 'needs_manual_check')
are left as they are; the daily review reads both.

Runs on the VPS after the job-board check (vps/run_detector.sh). One DB
connection (remote MySQL user is capped at 500 connections/hour).

Usage:
    python mark_hot_flags.py            # tag flags
    python mark_hot_flags.py --dry-run  # print what would be tagged
    python mark_hot_flags.py --days 7   # look back further (testing)
"""
import os
import re
import sys

import mysql.connector

POSITION = re.compile(
    r"\b(violin|viola|cello|double bass|bass(?! clef)|contrabass|flute|piccolo|oboe|english horn|clarinet|"
    r"bassoon|contrabassoon|horn|trumpet|trombone|tuba|timpani|percussion|harp|keyboard|piano|celest[ae]|"
    r"organ|saxophone|guitar|concertmaster|principal|section (?:player|violin|viola|cello|bass))\b",
    re.I,
)
WHEN = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|"
    r"\bdeadline\b|\baudition(s|ing)?\b|\bresum[eé]s? due\b|\bapply by\b",
    re.I,
)
# Lines that mention instruments + dates but are concerts/marketing, not openings.
NOISE = re.compile(r"tickets?|concert|performance|subscribe|donat|featuring|soloist|program notes|\bwith\b.*\bsymphony\b", re.I)
WINDOW = 3


def is_hot(diff):
    lines = (diff or "").splitlines()
    added = [l[1:].strip() for l in lines if l.startswith("+") and not l.startswith("+++")]
    removed = {l[1:].strip() for l in lines if l.startswith("-") and not l.startswith("---")}
    added = [l for l in added if l and l not in removed]
    for i, line in enumerate(added):
        if not POSITION.search(line) or NOISE.search(line):
            continue
        if any(WHEN.search(l) for l in added[i:i + WINDOW + 1]):
            return line
    return None


def main():
    dry = "--dry-run" in sys.argv
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 1.5
    conn = mysql.connector.connect(
        host=os.environ["DB_HOST"], user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"], charset="utf8mb4", connection_timeout=20,
    )
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT f.id, o.name, f.diff_summary FROM url_change_flags f JOIN orchestras o ON o.id = f.orchestra_id
           WHERE f.detector = 'c4a' AND f.failure_reason IS NULL
             AND f.detected_at > NOW() - INTERVAL %s HOUR""" + ("" if dry and "--days" in sys.argv else " AND f.status = 'unreviewed'"),
        (int(days * 24),),
    )
    hot = []
    for f in cur.fetchall():
        hit = is_hot(f["diff_summary"])
        if hit:
            hot.append(f["id"])
            print(f"[HOT] flag {f['id']} {f['name']}: {hit[:120]}")
    if hot and not dry:
        cur.execute(
            "UPDATE url_change_flags SET failure_reason='likely_new_audition' WHERE id IN (%s)" % ",".join(["%s"] * len(hot)),
            hot,
        )
        conn.commit()
    conn.close()
    print(f"Hot-flag triage: {len(hot)} likely new audition posting(s){' (dry run)' if dry else ''}.")


if __name__ == "__main__":
    main()
