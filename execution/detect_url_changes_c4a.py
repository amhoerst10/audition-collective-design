"""
Nightly content-change detector built on Crawl4AI (a real headless browser),
replacing the requests+BeautifulSoup detector in detect_url_changes.py.

Why: the old detector could not read ~87 of 408 orchestra pages (bot-blocked
403/406s, redirects it didn't follow, SSL/timeouts). A 2026-09-24 evaluation
showed Crawl4AI reads 70 of those 87 and matched 6/6 hand-verified orchestras
exactly. See directives/URL_CHANGE_DETECTION.md.

Every orchestra ends up in exactly one bucket per run:
  - read OK, unchanged         -> nothing
  - read OK, content changed   -> flag status='unreviewed' with a unified diff
  - blocked (Cloudflare etc.)  -> flag status='needs_manual_check', reason 'blocked'
  - page gone (404/410)        -> flag status='needs_manual_check', reason 'dead_link'
  - redirected to a new URL    -> flag status='needs_manual_check', reason 'moved'
                                  (with suggested_url); content is still diffed
  - unreachable after retry    -> flag status='needs_manual_check', reason 'unreachable'

Manual-check flags are de-duplicated so the queue doesn't refill every night:
no new flag if the same orchestra+reason already has an open one, or had one
in the last 7 days.

Runs on the VPS inside the ac-crawler Docker image (Crawl4AI + MySQL
connector); see vps/ in the audition-collective-design repo.

Usage:
    python detect_url_changes_c4a.py              # all orchestras
    python detect_url_changes_c4a.py --limit 10   # smoke test
    python detect_url_changes_c4a.py --ids 44,69  # specific orchestras
"""
import asyncio
import difflib
import hashlib
import os
import random
import re
import sys
import time
from datetime import datetime
from urllib.parse import urlparse

import mysql.connector
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

DETECTOR = "c4a"
# Kept deliberately gentle: after several back-to-back test crawls (2026-09-24/25)
# Cloudflare challenges on the VPS IP jumped from 9 to ~48, then fell back to
# 11 once crawling dropped to once a night. Fewer parallel requests, a random
# pause per site, and a shuffled order each night keep the IP's reputation up.
CONCURRENCY = 2
POLITE_DELAY_RANGE = (2.0, 6.0)
DEDUPE_DAYS = 7
PER_SITE_TIMEOUT = 120

CONFIG = {
    "host": os.environ["DB_HOST"],
    "user": os.environ["DB_USER"],
    "password": os.environ["DB_PASSWORD"],
    "database": os.environ["DB_NAME"],
    "charset": "utf8mb4",
    "connection_timeout": 20,
}

# Same living denylist as detect_url_changes.py -- keep both in sync with the
# directive's "Noise Denylist" section.
NOISE_PATTERNS = [
    re.compile(r"©\s*\d{4}.*", re.I),
    re.compile(r"copyright\s*©?\s*\d{4}.*", re.I),
    re.compile(r"all rights reserved.*", re.I),
    re.compile(r"last updated[:\s].*", re.I),
    re.compile(r"page generated[:\s].*", re.I),
    re.compile(r"^\s*\d{4}\s*$"),
    re.compile(r"^\s*\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:?\d{2}|Z)?\s*$"),
    re.compile(r"^\s*[\w.\-]*-?admin\s*$", re.I),
    re.compile(r"^\s*(posted|written|updated)\s+by\s+.*$", re.I),
    re.compile(r"^\s*printed\s+\d{1,2}/\d{1,2}/\d{2,4}\s*-\s*\d{1,2}:\d{2}:\d{2}\s*$", re.I),
    # Must require 2+ words -- a 1-word version caused the 2026-09-22 regression.
    re.compile(
        r"^\s*(concert|seating|preferred|accessible|other|name|desired|location|select|type|group)"
        r"([\s,]+(and/or|and|or)?[\s,]*(concert|seating|preferred|accessible|other|name|desired|location|select|type|group)){1,4}"
        r"[\s,]*$",
        re.I,
    ),
]
# Found on the first Crawl4AI noise test (two full runs 2 hours apart,
# 2026-09-24): page widgets that render on some loads and not others, and
# live countdown/clock text.
NOISE_PATTERNS += [
    re.compile(r"^\s*skip to (main )?content\s*$", re.I),
    re.compile(r"^\s*(cart|basket|account|checkout|secondary|notifications|opens in new window|pdf download)\s*$", re.I),
    re.compile(r"your cart is empty|^\s*subtotal\s*\$|drag here to send|email us for a quick response", re.I),
    re.compile(r"audioeye|we use (essential )?cookies|cookie (settings|preferences|policy)|^\s*(accept|decline|reject)( all)?\s*$", re.I),
    re.compile(r"^\s*\d+d\s+\d{1,2}:\d{2}:\d{2}\s*$"),               # countdown "23d 15:59:15"
    re.compile(r"^\s*\d{1,3}\s*(days?|hours?|minutes?|seconds?|mins?|secs?)\s*$", re.I),
    re.compile(r"\b\d{1,2}:\d{2}:\d{2}\b.*\b(WIB|UTC|GMT)\b|^\s*\d{1,2}:\d{2}:\d{2}\s*$", re.I),
    # Second noise test (2026-09-25): all 12 "changes" between two runs 90
    # minutes apart were these.
    re.compile(r"press (option|alt)\+\d for screen-reader mode|accessibility (preferences|screen-reader guide)", re.I),
    re.compile(r"partners use cookies|vendors seeking consent|manage (consent|preferences)|consent preferences", re.I),
    re.compile(r"^\s*\d{1,2}\s*$"),  # lone countdown digits
    re.compile(r"^\s*(subscribe( for email updates| now)?|sign up( now)?|type your (name|email)|stay up to date.*|subscribe to .*|join our (mailing|email) list.*)\s*$", re.I),
    re.compile(r"\|\s*(MON|TUE|WED|THU|FRI|SAT|SUN),\s*[A-Z]{3}\s+\d{1,2}\s+at\s+\d", re.I),  # concert-picker options
    # Third noise test (2026-09-25): the 4 remaining flickers.
    re.compile(r"^\s*(word|excel|powerpoint|document|pdf) download\s*$|explore your accessibility options", re.I),
    re.compile(r"^\s*(submit|join the list|contact us|✘|unable to send, please try again\.?)\s*$", re.I),
    re.compile(r"^\s*concert name( and/or)?\s*$", re.I),
]
EMPHASIS = re.compile(r"\*\*|__")
HONEYPOT_MARKER = "this field is for validation purposes and should be left unchanged."

# Do NOT exclude <form> or <header>: the first full run (2026-09-24) showed
# some sites wrap the entire page in a <form> (Seattle Opera kept 1 char of
# 5,825; Grand Rapids 167 of 2,651) and some WordPress themes put page
# content inside <header> (Berkeley, Toledo, Dallas Winds). Form-driven noise
# is handled by the honeypot rule and NOISE_PATTERNS instead.
EXCLUDED_TAGS = ["nav", "footer", "script", "style", "noscript", "svg"]

# Bot-challenge interstitials that come back with a normal status code (e.g.
# Virginia Symphony returns 202 with "Checking the site connection
# security"). Without this they were misread as near-empty dead pages, and
# in the evaluation some ~305-char challenge pages were even counted as
# successes.
CHALLENGE_PAGE = re.compile(
    r"checking the site connection security|robot-suspicion|requires cookies to be enabled|"
    r"just a moment|checking your browser|verify you are human|attention required|"
    r"enable javascript and cookies|access denied|request unsuccessful|incapsula|"
    r"ddos protection|security check",
    re.I,
)

IMG_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK_MD = re.compile(r"\[([^\]]*)\]\([^)]*\)")
BLOCKED_STATUS = {401, 403, 406, 429}
DEAD_STATUS = {404, 410}


def clean_markdown(md):
    md = IMG_MD.sub("", md)
    md = LINK_MD.sub(r"\1", md)  # link targets carry tracking params that rotate
    md = EMPHASIS.sub("", md)  # "18** hours" defeated the countdown pattern
    lines = [l.strip().strip("#*_> ").strip() for l in md.splitlines()]
    lines = [l for l in lines if l]
    lines = [
        l for i, l in enumerate(lines)
        if l.lower() != HONEYPOT_MARKER
        and not (i + 1 < len(lines) and lines[i + 1].lower() == HONEYPOT_MARKER)
    ]
    return "\n".join(l for l in lines if not any(p.search(l) for p in NOISE_PATTERNS))


def norm_url(u):
    p = urlparse(u or "")
    host = p.netloc.lower().removeprefix("www.")
    return host + p.path.rstrip("/").lower()


def host_of(u):
    return urlparse(u or "").netloc.lower().removeprefix("www.")


def classify(r, original_url):
    """Return (bucket, detail). bucket in ok|blocked|dead_link|unreachable."""
    err = (r.error_message or "") if r else ""
    status = r.status_code if r else None
    if r is None:
        return "unreachable", "no result"
    if "anti-bot" in err.lower() or status in BLOCKED_STATUS:
        return "blocked", f"HTTP {status}: {err[:120]}"
    if status in DEAD_STATUS:
        return "dead_link", f"HTTP {status}"
    if not r.success:
        return "unreachable", err[:160]
    return "ok", None


async def fetch(crawler, url, cfg):
    for attempt in range(2):
        try:
            r = await crawler.arun(url=url, config=cfg)
            if r.success or attempt == 1 or (r.status_code and r.status_code < 500):
                return r
        except Exception:
            if attempt == 1:
                return None
        await asyncio.sleep(5)
    return None


def db():
    return mysql.connector.connect(**CONFIG)


def recent_manual_flag_exists(cur, orchestra_id, reason):
    cur.execute(
        """SELECT 1 FROM url_change_flags
           WHERE orchestra_id=%s AND detector=%s AND failure_reason=%s
             AND (status='needs_manual_check' OR detected_at > NOW() - INTERVAL %s DAY)
           LIMIT 1""",
        (orchestra_id, DETECTOR, reason, DEDUPE_DAYS),
    )
    return cur.fetchone() is not None


def add_manual_flag(cur, orchestra_id, reason, detail, suggested_url=None):
    if recent_manual_flag_exists(cur, orchestra_id, reason):
        return False
    cur.execute(
        """INSERT INTO url_change_flags
           (orchestra_id, detected_at, diff_summary, status, detector, failure_reason, suggested_url)
           VALUES (%s, NOW(), %s, 'needs_manual_check', %s, %s, %s)""",
        (orchestra_id, detail, DETECTOR, reason, suggested_url),
    )
    return True


def get_snapshot(cur, orchestra_id):
    cur.execute("SELECT clean_text, content_hash FROM url_change_snapshots_c4a WHERE orchestra_id=%s", (orchestra_id,))
    return {"snap": cur.fetchone()}


def stable_diff(old_text, text1, text2):
    """Lines added/removed in BOTH independent reads vs the baseline. Widgets
    that render on one load but not the other drop out here."""
    old, a1, a2 = set(old_text.splitlines()), set(text1.splitlines()), set(text2.splitlines())
    added = (a1 - old) & (a2 - old)
    removed = (old - a1) & (old - a2)
    if not added and not removed:
        return None
    full = difflib.unified_diff(old_text.splitlines(), text2.splitlines(), "previous", "current", lineterm="")
    keep = [l for l in full if l.startswith(("---", "+++", "@@"))
            or (l.startswith("+") and l[1:] in added) or (l.startswith("-") and l[1:] in removed)]
    return "\n".join(keep)


def record_content(cur, o, text, final_url, status, tally, diff=None, flaky=False):
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    cur.execute("SELECT clean_text, content_hash FROM url_change_snapshots_c4a WHERE orchestra_id=%s", (o["id"],))
    snap = cur.fetchone()
    if snap is not None and flaky:
        cur.execute("UPDATE url_change_snapshots_c4a SET last_checked_at=NOW() WHERE orchestra_id=%s", (o["id"],))
        tally["flaky"] += 1
        return "FLKY"
    if snap is None:
        cur.execute(
            """INSERT INTO url_change_snapshots_c4a
               (orchestra_id, clean_text, content_hash, final_url, last_status, last_checked_at, last_changed_at)
               VALUES (%s,%s,%s,%s,%s,NOW(),NOW())""",
            (o["id"], text, h, final_url, status),
        )
        tally["baseline"] += 1
        return "BASE"
    if snap[1] == h:
        cur.execute(
            "UPDATE url_change_snapshots_c4a SET last_checked_at=NOW(), final_url=%s, last_status=%s WHERE orchestra_id=%s",
            (final_url, status, o["id"]),
        )
        tally["unchanged"] += 1
        return "SAME"
    if diff is None:
        diff = "\n".join(difflib.unified_diff(snap[0].splitlines(), text.splitlines(), "previous", "current", lineterm=""))
    cur.execute(
        """INSERT INTO url_change_flags (orchestra_id, detected_at, diff_summary, status, detector)
           VALUES (%s, NOW(), %s, 'unreviewed', %s)""",
        (o["id"], diff[:60000], DETECTOR),
    )
    cur.execute(
        """UPDATE url_change_snapshots_c4a SET clean_text=%s, content_hash=%s, final_url=%s,
           last_status=%s, last_checked_at=NOW(), last_changed_at=NOW() WHERE orchestra_id=%s""",
        (text, h, final_url, status, o["id"]),
    )
    tally["changed"] += 1
    return "FLAG"


_CONN = None


def write(o, fn, *args):
    """Run DB work on ONE shared connection, reconnecting only if it drops.

    Never open a connection per call: the Hostinger MySQL user is capped at
    500 new connections/hour, shared with the live site's Audition Board. A
    connection-per-call version (2026-09-24) hit the cap mid-run, lost ~135
    orchestras' results, and would have locked the Audition Board out of the
    database until the hour reset. Safe to share: the crawler runs on one
    asyncio thread, so these calls never overlap.
    """
    global _CONN
    for attempt in range(2):
        try:
            if _CONN is None or not _CONN.is_connected():
                _CONN = db()
            cur = _CONN.cursor()
            out = fn(cur, *args)
            _CONN.commit()
            cur.close()
            return out
        except mysql.connector.Error as e:
            _CONN = None
            if attempt == 1:
                print(f"  [DBER] [{o['id']}] {o['name']}: {e}", flush=True)
                return None
            time.sleep(3)


async def process(crawler, cfg, o, sem, tally):
    async with sem:
        await asyncio.sleep(random.uniform(*POLITE_DELAY_RANGE))
        # Hard cap per orchestra: page_timeout alone didn't stop Phoenix
        # Symphony's page from hanging the browser for 2+ hours on the first
        # full run (2026-09-24), which blocked the whole job from finishing.
        try:
            r = await asyncio.wait_for(fetch(crawler, o["url"], cfg), timeout=PER_SITE_TIMEOUT)
        except asyncio.TimeoutError:
            write(o, add_manual_flag, o["id"], "unreachable", f"Hung past {PER_SITE_TIMEOUT}s hard timeout")
            tally["unreachable"] += 1
            print(f"  [HUNG ] [{o['id']}] {o['name']} -- killed after {PER_SITE_TIMEOUT}s", flush=True)
            return
        bucket, detail = classify(r, o["url"])
        if bucket != "ok":
            new = write(o, add_manual_flag, o["id"], bucket, detail)
            tally[bucket] += 1
            print(f"  [{bucket.upper()[:5]:5}] [{o['id']}] {o['name']} -- {detail}{'' if new else ' (already queued)'}", flush=True)
            return
        md = (r.markdown.raw_markdown if hasattr(r.markdown, "raw_markdown") else str(r.markdown or "")) or ""
        if len(md) < 3000 and CHALLENGE_PAGE.search(md):
            new = write(o, add_manual_flag, o["id"], "blocked", f"Bot-challenge page (HTTP {r.status_code})")
            tally["blocked"] += 1
            print(f"  [BLOCK] [{o['id']}] {o['name']} -- challenge page{'' if new else ' (already queued)'}", flush=True)
            return
        final_url = getattr(r, "redirected_url", None) or o["url"]
        if norm_url(final_url) != norm_url(o["url"]):
            same = host_of(final_url) == host_of(o["url"])
            reason = "moved_same_site" if same else "moved_offsite"
            write(o, add_manual_flag, o["id"], reason, f"Redirected to {final_url}", final_url)
            tally[reason] += 1
            if not same:
                # The content isn't the orchestra's (e.g. Arkansas Phil's URL
                # now serves a gambling site with live numbers); diffing it
                # only produces noise. The moved_offsite flag is the signal.
                return
        text = clean_markdown(md)
        if len(text) < 200:
            write(o, add_manual_flag, o["id"], "dead_link", f"Page loaded but only {len(text)} chars of content")
            tally["dead_link"] += 1
            print(f"  [DEAD ] [{o['id']}] {o['name']} -- near-empty page", flush=True)
            return
        diff, flaky = None, False
        got = write(o, get_snapshot, o["id"])
        snap = got["snap"] if got else None
        if snap and snap[1] != hashlib.sha256(text.encode("utf-8")).hexdigest():
            # Looks changed: read the page a second time and keep only the
            # lines that changed in both reads.
            try:
                r2 = await asyncio.wait_for(fetch(crawler, o["url"], cfg), timeout=PER_SITE_TIMEOUT)
            except asyncio.TimeoutError:
                r2 = None
            if r2 is not None and r2.success:
                md2 = (r2.markdown.raw_markdown if hasattr(r2.markdown, "raw_markdown") else str(r2.markdown or "")) or ""
                text2 = clean_markdown(md2)
                diff = stable_diff(snap[0], text, text2)
                if diff is None:
                    flaky = True
                else:
                    text = text2
        result = write(o, record_content, o, text, final_url, r.status_code, tally, diff, flaky)
        if result in ("BASE", "FLAG"):
            print(f"  [{result}] [{o['id']}] {o['name']}", flush=True)


STALE_UNDATED_DAYS = 60


def queue_stale_undated(cur):
    """Listings with no final audition date can never expire via the nightly
    purge, so re-queue any not verified in STALE_UNDATED_DAYS for a manual
    check. (Alabama Symphony's undated Principal Trumpet lingered after its
    audition had passed, 2026-09-26.)"""
    cur.execute(
        """SELECT DISTINCT a.orchestra_id FROM auditions a
           WHERE a.final_audition IS NULL
             AND a.position <> 'No auditions reported at this time'
             AND (a.last_verified_at IS NULL OR a.last_verified_at < NOW() - INTERVAL %s DAY)""",
        (STALE_UNDATED_DAYS,),
    )
    queued = 0
    for (oid,) in cur.fetchall():
        if add_manual_flag(cur, oid, "stale_undated",
                           f"Undated listing(s) not verified in {STALE_UNDATED_DAYS}+ days; confirm still open"):
            queued += 1
    # A preliminary date with no final is always a capture error (a single
    # audition date belongs in final_audition) -- Waterloo-Cedar Falls,
    # 2026-09-26. Queue immediately rather than waiting 60 days.
    cur.execute(
        """SELECT DISTINCT orchestra_id FROM auditions
           WHERE preliminary_audition IS NOT NULL AND final_audition IS NULL"""
    )
    for (oid,) in cur.fetchall():
        if add_manual_flag(cur, oid, "prelim_no_final",
                           "Listing has a preliminary date but no final audition date; likely a single audition date stored in the wrong column"):
            queued += 1
    return queued


def load_orchestras(limit=None, ids=None):
    conn = db()
    cur = conn.cursor(dictionary=True)
    q = "SELECT id, name, state, url FROM orchestras"
    if ids:
        q += f" WHERE id IN ({','.join(str(int(i)) for i in ids)})"
    q += " ORDER BY state, name"
    if limit:
        q += f" LIMIT {int(limit)}"
    cur.execute(q)
    rows = cur.fetchall()
    conn.close()
    return rows


async def main():
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    ids = sys.argv[sys.argv.index("--ids") + 1].split(",") if "--ids" in sys.argv else None
    orchestras = load_orchestras(limit, ids)
    random.shuffle(orchestras)
    started = datetime.now()
    print(f"{started:%Y-%m-%d %H:%M:%S} Crawl4AI detector: {len(orchestras)} orchestras", flush=True)

    tally = dict(baseline=0, unchanged=0, changed=0, flaky=0, blocked=0, dead_link=0, unreachable=0,
                 moved_same_site=0, moved_offsite=0)
    cfg = CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        page_timeout=45000,
        wait_until="domcontentloaded",
        delay_before_return_html=2.0,
        excluded_tags=EXCLUDED_TAGS,
        magic=True,
        simulate_user=True,
        override_navigator=True,
        verbose=False,
    )
    sem = asyncio.Semaphore(CONCURRENCY)
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, enable_stealth=True, verbose=False)) as crawler:
        await asyncio.gather(*(process(crawler, cfg, o, sem, tally) for o in orchestras))

    if not ids and not limit:
        stale = write({"id": 0, "name": "stale-undated sweep"}, queue_stale_undated)
        tally["stale_undated"] = stale or 0

    mins = (datetime.now() - started).total_seconds() / 60
    print(f"Done in {mins:.1f} min. " + ", ".join(f"{k}={v}" for k, v in tally.items()), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
