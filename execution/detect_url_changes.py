"""
Daily content-diff checker for every orchestras.url. Extracts and cleans the
visible body text of each page, strips known noise (copyright lines, "last
updated" stamps, etc -- see directives/URL_CHANGE_DETECTION.md's Noise
Denylist), and diffs it against the last stored snapshot. A real text change
gets a flag row in url_change_flags with a unified diff attached, so a human
or agent can judge "real audition posting" vs "noise we should add to the
denylist" at a glance -- rather than trusting a bare hash match/mismatch.

First run for any given orchestra just stores a baseline snapshot (nothing to
diff against yet) and produces no flag. This is expected, not a bug.

Usage:
    python execution/detect_url_changes.py                  # check all orchestras
    python execution/detect_url_changes.py --state Wyoming   # check one state only
    python execution/detect_url_changes.py --limit 10        # smoke-test on a few rows
"""
import os
import re
import sys
import time
import hashlib
import difflib
from datetime import datetime

import requests
import mysql.connector
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
    'charset': 'utf8mb4',
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
}

# Living list -- see directives/URL_CHANGE_DETECTION.md "Noise Denylist".
# Add patterns here as real runs surface false-positive sources; keep the
# directive's copy in sync when you do.
NOISE_PATTERNS = [
    re.compile(r'©\s*\d{4}.*', re.IGNORECASE),
    re.compile(r'copyright\s*©?\s*\d{4}.*', re.IGNORECASE),
    re.compile(r'all rights reserved.*', re.IGNORECASE),
    re.compile(r'last updated[:\s].*', re.IGNORECASE),
    re.compile(r'page generated[:\s].*', re.IGNORECASE),
    re.compile(r'^\s*\d{4}\s*$'),  # a bare standalone 4-digit year on its own line
    # ISO 8601 timestamps (WordPress post-meta "modified date" lines commonly
    # leak into visible text, e.g. "2026-07-14T18:18:20+00:00") -- these bump
    # on unrelated content edits, not just real audition changes.
    re.compile(r'^\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:?\d{2}|Z)?\s*$'),
    # WordPress/CMS author bylines standalone on their own line, e.g.
    # "richard-admin", "admin", "posted-by-jsmith".
    re.compile(r'^\s*[\w.\-]*-?admin\s*$', re.IGNORECASE),
    re.compile(r'^\s*(posted|written|updated)\s+by\s+.*$', re.IGNORECASE),
    # "Page printed" timestamps some sites render live server-side on every
    # request (e.g. "Printed 9/18/26 - 7:04:37") -- confirmed on Portland
    # Baroque Orchestra's page, ticking every single check regardless of any
    # real content change. Classic case of exactly the failure mode this
    # whole tool was designed to avoid (see directive intro).
    re.compile(r'^\s*printed\s+\d{1,2}/\d{1,2}/\d{2,4}\s*-\s*\d{1,2}:\d{2}:\d{2}\s*$', re.IGNORECASE),
    # Accessibility-accommodation / ticket-request form fragments (e.g. North
    # Carolina Symphony's "Request Accommodations" form embeds a "Desired
    # Concert" dropdown per upcoming show, defaulting to whichever concert is
    # next -- as the calendar advances the default rotates, and
    # BeautifulSoup's text extraction fragments the surrounding labels into
    # short word-soup lines like "Concert Other, Seating"). A line made up
    # entirely of 1-5 of these known form-vocabulary words is essentially
    # never real audition content on its own.
    re.compile(
        r'^\s*(concert|seating|preferred|accessible|other|name|desired|location|select|type|group)'
        r'([\s,]+(and|or)?[\s,]*(concert|seating|preferred|accessible|other|name|desired|location|select|type|group)){0,4}'
        r'[\s,]*$',
        re.IGNORECASE
    ),
]

STRIP_TAGS = ['script', 'style', 'nav', 'header', 'footer', 'noscript', 'svg']


def clean_text_from_html(html):
    soup = BeautifulSoup(html, 'html.parser')
    for tag_name in STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    raw_text = soup.get_text(separator='\n')
    lines = [line.strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]  # drop blank lines

    # Gravity Forms (a common WordPress form plugin) injects a randomized
    # decoy field label as an anti-spam honeypot on EVERY page load --
    # confirmed on the first real full-scan run (Atlanta Opera, Quad City
    # Symphony): the label randomly rotates between "Name"/"Phone"/"URL"/
    # "X/Twitter"/"Instagram"/"LinkedIn"/"Comments"/"Company"/etc, always
    # immediately followed by the constant marker line below. Drop both the
    # random label and the marker line -- neither is real page content, and
    # the label alone would cause a "content changed" flag on nearly every
    # single check of any site using this plugin.
    HONEYPOT_MARKER = 'this field is for validation purposes and should be left unchanged.'
    lines = [
        line for i, line in enumerate(lines)
        if line.lower() != HONEYPOT_MARKER
        and not (i + 1 < len(lines) and lines[i + 1].lower() == HONEYPOT_MARKER)
    ]

    kept = []
    for line in lines:
        if any(p.search(line) for p in NOISE_PATTERNS):
            continue
        kept.append(line)

    return '\n'.join(kept)


def hash_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def fetch_orchestras(state_filter=None, limit=None):
    conn = mysql.connector.connect(**CONFIG)
    cur = conn.cursor(dictionary=True)
    query = "SELECT id, name, state, url FROM orchestras"
    params = ()
    if state_filter:
        query += " WHERE state = %s"
        params = (state_filter,)
    query += " ORDER BY state, name"
    if limit:
        query += f" LIMIT {int(limit)}"
    cur.execute(query, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


def get_snapshot(cur, orchestra_id):
    cur.execute(
        "SELECT clean_text, content_hash FROM url_change_snapshots WHERE orchestra_id = %s",
        (orchestra_id,)
    )
    return cur.fetchone()


def upsert_snapshot(cur, orchestra_id, clean_text, content_hash, changed):
    now = datetime.now()
    cur.execute(
        "SELECT orchestra_id FROM url_change_snapshots WHERE orchestra_id = %s",
        (orchestra_id,)
    )
    exists = cur.fetchone()
    if exists:
        if changed:
            cur.execute(
                """UPDATE url_change_snapshots
                   SET clean_text=%s, content_hash=%s, last_checked_at=%s, last_changed_at=%s
                   WHERE orchestra_id=%s""",
                (clean_text, content_hash, now, now, orchestra_id)
            )
        else:
            cur.execute(
                "UPDATE url_change_snapshots SET last_checked_at=%s WHERE orchestra_id=%s",
                (now, orchestra_id)
            )
    else:
        cur.execute(
            """INSERT INTO url_change_snapshots
               (orchestra_id, clean_text, content_hash, last_checked_at, last_changed_at)
               VALUES (%s, %s, %s, %s, %s)""",
            (orchestra_id, clean_text, content_hash, now, now)
        )


def insert_flag(cur, orchestra_id, diff_summary):
    cur.execute(
        """INSERT INTO url_change_flags (orchestra_id, detected_at, diff_summary, status)
           VALUES (%s, %s, %s, 'unreviewed')""",
        (orchestra_id, datetime.now(), diff_summary)
    )


def process_one(o, conn, timeout, tally):
    """Fetch+diff a single orchestra. Returns ('ok', conn) or ('net_err', conn)
    -- net_err means a DNS/connection-level failure worth retrying in a later
    sweep; anything else (HTTP status, DB error after its own internal
    retries) is counted as a permanent skip for this run and returns 'ok' so
    it isn't retried again."""
    resp = None
    last_exc = None
    for attempt in range(3):
        try:
            resp = requests.get(o['url'], headers=HEADERS, timeout=timeout, allow_redirects=True)
            last_exc = None
            break
        except requests.exceptions.RequestException as e:
            last_exc = e
            if attempt < 2:
                time.sleep(2)

    if last_exc is not None:
        print(f"  [ERR ] [{o['id']}] {o['name']} ({o['state']}) -> {type(last_exc).__name__} (after retries)")
        return 'net_err', conn

    if resp.status_code >= 400:
        print(f"  [ERR ] [{o['id']}] {o['name']} ({o['state']}) -> HTTP {resp.status_code}, skipping")
        tally['errors'] += 1
        return 'ok', conn

    # requests defaults to ISO-8859-1 when the Content-Type header doesn't
    # declare a charset (per HTTP spec), which mangles UTF-8 pages into
    # mojibake -- and since that garbling isn't stable run-to-run, it would
    # show up as spurious diffs. Fall back to apparent_encoding (real
    # byte-content detection) whenever the response didn't declare charset.
    if 'charset' not in resp.headers.get('content-type', '').lower():
        resp.encoding = resp.apparent_encoding
    new_text = clean_text_from_html(resp.text)
    new_hash = hash_text(new_text)

    # The remote MySQL connection gets forcibly dropped mid-run under this
    # environment's known network flakiness -- not just when idle, but
    # sometimes actively (a fresh ping can succeed and the very next query
    # still fail). Retry the whole read-then-write unit against a freshly
    # reconnected connection rather than trusting one long-lived connection.
    for db_attempt in range(3):
        try:
            cur = conn.cursor(dictionary=True)
            snapshot = get_snapshot(cur, o['id'])

            if snapshot is None:
                upsert_snapshot(cur, o['id'], new_text, new_hash, changed=True)
                conn.commit()
                print(f"  [BASE] [{o['id']}] {o['name']} ({o['state']}) -> baseline stored")
                tally['baselines'] += 1
            elif snapshot['content_hash'] == new_hash:
                upsert_snapshot(cur, o['id'], new_text, new_hash, changed=False)
                conn.commit()
                tally['unchanged'] += 1
            else:
                old_lines = snapshot['clean_text'].splitlines()
                new_lines = new_text.splitlines()
                diff = '\n'.join(difflib.unified_diff(
                    old_lines, new_lines,
                    fromfile='previous', tofile='current', lineterm=''
                ))
                insert_flag(cur, o['id'], diff)
                upsert_snapshot(cur, o['id'], new_text, new_hash, changed=True)
                conn.commit()
                print(f"  [FLAG] [{o['id']}] {o['name']} ({o['state']}) -> content changed, flag created")
                tally['changed'] += 1
            return 'ok', conn
        except mysql.connector.Error as e:
            if db_attempt < 2:
                time.sleep(2)
                try:
                    conn.close()
                except mysql.connector.Error:
                    pass
                conn = mysql.connector.connect(**CONFIG)
            else:
                print(f"  [ERR ] [{o['id']}] {o['name']} ({o['state']}) -> DB error after retries: {e}, skipping")
                tally['errors'] += 1
                return 'ok', conn


def run(state_filter=None, limit=None, timeout=10):
    orchestras = fetch_orchestras(state_filter, limit)
    print(f"Checking {len(orchestras)} orchestra URL(s) for content changes...\n")

    conn = mysql.connector.connect(**CONFIG)
    tally = {'baselines': 0, 'unchanged': 0, 'changed': 0, 'errors': 0}

    pending = orchestras
    # This environment's router drops DNS resolution intermittently under
    # sustained request volume (confirmed via nslookup on "failed" domains
    # resolving fine seconds later) -- unrelated to any given site's health.
    # Do up to 3 full sweeps, retrying only the URLs that failed at the
    # network level each time, with a longer cooldown between sweeps than
    # the per-request retry gets.
    for round_num in range(1, 4):
        if not pending:
            break
        if round_num > 1:
            print(f"\nRetry sweep {round_num - 1}: re-checking {len(pending)} network-failed URL(s) after a cooldown...\n")
            time.sleep(15)
        still_failing = []
        for o in pending:
            status, conn = process_one(o, conn, timeout, tally)
            if status == 'net_err':
                still_failing.append(o)
            time.sleep(0.3)  # be polite
        pending = still_failing

    if pending:
        tally['errors'] += len(pending)
        print(f"\n{len(pending)} URL(s) still failing at the network level after 3 sweeps -- treated as real errors this run:")
        for o in pending:
            print(f"    [{o['id']}] {o['name']} ({o['state']}) -- {o['url']}")

    conn.close()

    print(f"\nDone. {tally['baselines']} new baselines, {tally['unchanged']} unchanged, "
          f"{tally['changed']} flagged, {tally['errors']} errors.")


if __name__ == "__main__":
    state = None
    limit = None
    if "--state" in sys.argv:
        state = sys.argv[sys.argv.index("--state") + 1]
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    run(state_filter=state, limit=limit)
