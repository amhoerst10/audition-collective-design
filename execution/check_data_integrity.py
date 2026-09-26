"""
Nightly data-integrity check: scans every audition row for patterns that
usually mean a capture error, and queues each affected orchestra for a
manual check (url_change_flags, status='needs_manual_check',
failure_reason='data_integrity', diff_summary = the specific issues).

Why: the project owner kept finding these by eye on the live board --
Alabama's undated Principal Trumpet that never expired, Waterloo's single
audition date stored as a preliminary, listings with a prelim and final but
no deadline. Checks are heuristics: a hit means "look at this," not "this
is wrong" (e.g. Atlanta's 2027 auditions legitimately have no deadline yet,
which is why the no-deadline check only fires within 120 days of the final).

Runs on the VPS after detect_url_changes_c4a.py (see vps/run_detector.sh).
Uses ONE DB connection -- the remote MySQL user is capped at 500
connections/hour.

Usage:
    python check_data_integrity.py            # queue flags
    python check_data_integrity.py --dry-run  # print findings only
"""
import os
import re
import sys
from collections import defaultdict
from datetime import date, timedelta

import mysql.connector

PLACEHOLDER = "No auditions reported at this time"
ALLOWED = {
    "Bass", "Bass Clarinet", "Bass Trombone", "Bassoon", "Celeste", "Cello", "Clarinet",
    "Contrabassoon", "Flute", "Guitar", "Harp", "Horn", "Keyboard", "Oboe", "Organ",
    "Percussion", "Piano", "Piano & Celeste", "Saxophone", "Timpani", "Trombone",
    "Trumpet", "Tuba", "Viola", "Violin", "N/A",
}
REASON_SUFFIX = re.compile(r"\((contact to schedule|video|rolling|postponed|sub list)", re.I)
NO_DEADLINE_WINDOW_DAYS = 120
FAR_FUTURE_DAYS = 548  # ~18 months
DEDUPE_DAYS = 7

# Position words that pin the instrument. Checked longest-first so "bass
# trombone" wins over "trombone" and "bass".
POSITION_INSTRUMENT = [
    ("bass clarinet", {"Bass Clarinet", "Clarinet"}),
    ("bass trombone", {"Bass Trombone", "Trombone"}),
    ("contrabassoon", {"Contrabassoon", "Bassoon"}),
    ("english horn", {"Oboe"}),
    ("piccolo", {"Flute"}),
    ("timpani", {"Timpani", "Percussion"}),
    ("violin", {"Violin"}),
    ("viola", {"Viola"}),
    ("cello", {"Cello"}),
    ("flute", {"Flute"}),
    ("oboe", {"Oboe"}),
    ("clarinet", {"Clarinet", "Bass Clarinet"}),
    ("bassoon", {"Bassoon", "Contrabassoon"}),
    ("trumpet", {"Trumpet"}),
    ("trombone", {"Trombone", "Bass Trombone"}),
    ("tuba", {"Tuba"}),
    ("harp", {"Harp"}),
    ("horn", {"Horn"}),
]


def issues_for(rows, today):
    """rows: one orchestra's audition rows. Returns a list of issue strings."""
    out = []
    real = [r for r in rows if r["position"] != PLACEHOLDER]
    if not rows:
        out.append("Orchestra has no audition rows at all (needs at least the placeholder)")
    if real and len(real) != len(rows):
        out.append("Placeholder row coexists with real listings")
    if len([r for r in rows if r["position"] == PLACEHOLDER]) > 1:
        out.append("Duplicate placeholder rows")

    seen = defaultdict(int)
    for r in real:
        key = (r["position"].strip().lower(), r["instrumentation"], r["final_audition"])
        seen[key] += 1
    for (pos, _, _), n in seen.items():
        if n > 1:
            out.append(f"Duplicate listing x{n}: {pos}")

    for r in real:
        p, d, pre, fin = r["position"], r["application_deadline"], r["preliminary_audition"], r["final_audition"]
        tag = f"'{p}'"
        if r["instrumentation"] not in ALLOWED:
            out.append(f"{tag}: instrumentation '{r['instrumentation']}' not in the allowed list")
        pl = p.lower()
        for word, allowed in POSITION_INSTRUMENT:
            if word in pl:
                if r["instrumentation"] not in allowed and "&" not in (r["instrumentation"] or ""):
                    out.append(f"{tag}: position says '{word}' but instrumentation is '{r['instrumentation']}'")
                break
        if pre and not fin:
            out.append(f"{tag}: preliminary date but no final (single audition date in the wrong column?)")
        if not fin and not REASON_SUFFIX.search(p):
            out.append(f"{tag}: no final date and no stated reason suffix")
        if d and fin and d > fin:
            out.append(f"{tag}: deadline {d} is after the final audition {fin}")
        if d and pre and d > pre:
            out.append(f"{tag}: deadline {d} is after the preliminary {pre}")
        if pre and fin and pre > fin:
            out.append(f"{tag}: preliminary {pre} is after the final {fin}")
        if fin and not d and today <= fin <= today + timedelta(days=NO_DEADLINE_WINDOW_DAYS):
            out.append(f"{tag}: final {fin} is within {NO_DEADLINE_WINDOW_DAYS} days but no application deadline")
        if fin and fin > today + timedelta(days=FAR_FUTURE_DAYS):
            out.append(f"{tag}: final {fin} is more than 18 months out (year typo?)")
        # The WP-Cron expiry purge fires ~15:45 UTC, so a final from yesterday
        # can legitimately still be present in the morning; allow one day.
        if fin and fin < today - timedelta(days=1):
            out.append(f"{tag}: final {fin} passed over a day ago but the listing is still present (purge missed it?)")
    return out


def main():
    dry = "--dry-run" in sys.argv
    conn = mysql.connector.connect(
        host=os.environ["DB_HOST"], user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"], charset="utf8mb4", connection_timeout=20,
    )
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, name FROM orchestras")
    orchestras = {r["id"]: r["name"] for r in cur.fetchall()}
    cur.execute("SELECT orchestra_id, position, instrumentation, application_deadline, "
                "preliminary_audition, final_audition FROM auditions")
    by_orch = defaultdict(list)
    for r in cur.fetchall():
        by_orch[r["orchestra_id"]].append(r)

    today = date.today()
    flagged = queued = total_issues = 0
    for oid, name in sorted(orchestras.items(), key=lambda kv: kv[1]):
        found = issues_for(by_orch.get(oid, []), today)
        if not found:
            continue
        flagged += 1
        total_issues += len(found)
        print(f"[{oid}] {name}")
        for f in found:
            print(f"    - {f}")
        if dry:
            continue
        # If a reviewer already confirmed this exact set of issues as correct
        # (e.g. an orchestra that genuinely publishes no deadline), don't
        # re-queue it every week. It re-queues as soon as the issues change.
        cur.execute(
            """SELECT diff_summary FROM url_change_flags WHERE orchestra_id=%s
               AND failure_reason='data_integrity' AND status='manual_check_done'
               ORDER BY reviewed_at DESC LIMIT 1""",
            (oid,),
        )
        prior = cur.fetchone()
        if prior and prior["diff_summary"] == "\n".join(found)[:60000]:
            continue
        cur.execute(
            """SELECT 1 FROM url_change_flags WHERE orchestra_id=%s AND failure_reason='data_integrity'
               AND (status='needs_manual_check' OR detected_at > NOW() - INTERVAL %s DAY) LIMIT 1""",
            (oid, DEDUPE_DAYS),
        )
        if cur.fetchone():
            continue
        cur.execute(
            """INSERT INTO url_change_flags (orchestra_id, detected_at, diff_summary, status, detector, failure_reason)
               VALUES (%s, NOW(), %s, 'needs_manual_check', 'integrity', 'data_integrity')""",
            (oid, "\n".join(found)[:60000]),
        )
        queued += 1
    if not dry:
        conn.commit()
    conn.close()
    print(f"\nIntegrity check: {total_issues} issue(s) across {flagged} orchestra(s); {queued} newly queued"
          f"{' (dry run, nothing queued)' if dry else ''}.")


if __name__ == "__main__":
    main()
