"""
Nightly job-board cross-check: reads musicalchairs.info's per-instrument job
pages (US postings only) and compares them with our database. A posting for
an orchestra we track, on an instrument we have no listing for, is queued for
manual review (url_change_flags, failure_reason='jobboard_mismatch') with the
posting details and link. Postings from US organizations we don't track are
logged as discovery leads.

Why: ~40 orchestras block our crawler (Cloudflare, by data-center IP), and
musicalchairs doesn't. It also catches openings we missed on sites we CAN read
-- a QA pass already confirmed Lyric Opera of Chicago's opening this way when
lyricopera.org refused every automated request. A mismatch is a lead, not a
verdict: postings can be stale or out of scope, and our scope rules (paid
instrumentalists, sub pay stated, final date not passed) still apply at
review.

Runs on the VPS after the detector (vps/run_detector.sh), inside the
ac-crawler image. ~20 polite requests a night. One DB connection (the remote
MySQL user is capped at 500 connections/hour).

Usage:
    python check_job_boards.py            # queue flags
    python check_job_boards.py --dry-run  # print findings only
"""
import asyncio
import difflib
import os
import random
import re
import sys
from collections import defaultdict

import mysql.connector
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

BASE = "https://www.musicalchairs.info"
# musicalchairs instrument slug -> our instrumentation values that count as a match
INSTRUMENT_PAGES = {
    "flute": {"Flute"}, "oboe": {"Oboe"}, "clarinet": {"Clarinet", "Bass Clarinet"},
    "bassoon": {"Bassoon", "Contrabassoon"}, "saxophone": {"Saxophone"},
    "french-horn": {"Horn"}, "trumpet": {"Trumpet"}, "trombone": {"Trombone", "Bass Trombone"},
    "tuba": {"Tuba"}, "violin": {"Violin"}, "viola": {"Viola"}, "cello": {"Cello"},
    "double-bass": {"Bass"}, "harp": {"Harp"}, "guitar": {"Guitar"},
    "piano": {"Piano", "Keyboard", "Piano & Celeste"}, "organ": {"Organ", "Keyboard"},
    "harpsichord": {"Keyboard"}, "timpani-percussion": {"Timpani", "Percussion"},
}
OUT_OF_SCOPE = re.compile(
    r"apprentice|academy|student|youth|fellowship|training|military|navy|army|air force|marine|"
    r"\busaf\b|west point|coast guard|\bband\b|cancelled",
    re.I,
)
DEDUPE_DAYS = 7
MATCH_CUTOFF = 0.86


def norm(name):
    n = name.lower()
    n = re.sub(r"\b(the|orchestra|symphony|philharmonic|of|and|inc|association|society)\b", " ", n)
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def parse_link(text):
    """musicalchairs link text: 'City, ST, United States\\n\\nPosted: ...\\n...\\nOrg\\nPosition\\n(contract)\\nClosing date: ...'"""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines or "United States" not in lines[0]:
        return None
    rest = [l for l in lines[1:] if not l.startswith("Posted:")]
    closing = next((l.split(":", 1)[1].strip() for l in rest if l.startswith("Closing date")), "n/a")
    rest = [l for l in rest if not l.startswith("Closing date")]
    contract = next((l.strip("()") for l in rest if l.startswith("(")), "")
    rest = [l for l in rest if not l.startswith("(")]
    if len(rest) < 2:
        return None
    return {"location": lines[0], "org": rest[0], "position": " ".join(rest[1:]), "contract": contract, "closing": closing}


async def fetch_postings():
    postings = []
    pages = list(INSTRUMENT_PAGES.items())
    random.shuffle(pages)
    cfg = CrawlerRunConfig(cache_mode=CacheMode.BYPASS, page_timeout=45000, delay_before_return_html=3, verbose=False)
    async with AsyncWebCrawler(config=BrowserConfig(headless=True, enable_stealth=True, verbose=False)) as crawler:
        for slug, instruments in pages:
            await asyncio.sleep(random.uniform(3, 7))
            try:
                r = await asyncio.wait_for(crawler.arun(url=f"{BASE}/{slug}/jobs", config=cfg), timeout=120)
            except Exception as e:
                print(f"  [ERR] {slug}: {type(e).__name__}")
                continue
            if not r.success:
                print(f"  [ERR] {slug}: {r.error_message}")
                continue
            for link in r.links.get("internal", []):
                href = link.get("href", "")
                if "/jobs/" not in href:
                    continue
                p = parse_link(link.get("text", ""))
                if p:
                    p.update(slug=slug, instruments=instruments, url=href.split("?")[0])
                    postings.append(p)
    return postings


def main():
    dry = "--dry-run" in sys.argv
    postings = asyncio.run(fetch_postings())
    conn = mysql.connector.connect(
        host=os.environ["DB_HOST"], user=os.environ["DB_USER"], password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"], charset="utf8mb4", connection_timeout=20,
    )
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, name FROM orchestras")
    orchs = cur.fetchall()
    by_norm = {norm(o["name"]): o for o in orchs}
    cur.execute("SELECT orchestra_id, instrumentation FROM auditions WHERE position <> 'No auditions reported at this time'")
    have = defaultdict(set)
    for r in cur.fetchall():
        have[r["orchestra_id"]].add(r["instrumentation"])

    mismatches = defaultdict(list)
    leads = []
    skipped = 0
    for p in postings:
        if OUT_OF_SCOPE.search(p["org"] + " " + p["position"] + " " + p["contract"]):
            skipped += 1
            continue
        n = norm(p["org"])
        match = by_norm.get(n)
        if not match:
            close = difflib.get_close_matches(n, by_norm.keys(), n=1, cutoff=MATCH_CUTOFF)
            match = by_norm[close[0]] if close else None
        if not match:
            leads.append(p)
            continue
        if not (have[match["id"]] & p["instruments"]):
            mismatches[match["id"]].append(p)

    queued = 0
    print(f"{len(postings)} US postings read; {skipped} skipped as out of scope.")
    for oid, ps in mismatches.items():
        name = next(o["name"] for o in orchs if o["id"] == oid)
        detail = "\n".join(
            f"musicalchairs posting we have no listing for: {p['position']} ({p['contract'] or 'terms n/a'}), "
            f"closing {p['closing']} -- {p['url']}" for p in ps)
        print(f"[{oid}] {name}\n  " + detail.replace("\n", "\n  "))
        if dry:
            continue
        cur.execute(
            """SELECT 1 FROM url_change_flags WHERE orchestra_id=%s AND failure_reason='jobboard_mismatch'
               AND (status='needs_manual_check' OR detected_at > NOW() - INTERVAL %s DAY) LIMIT 1""",
            (oid, DEDUPE_DAYS),
        )
        if cur.fetchone():
            continue
        cur.execute(
            """INSERT INTO url_change_flags (orchestra_id, detected_at, diff_summary, status, detector, failure_reason)
               VALUES (%s, NOW(), %s, 'needs_manual_check', 'jobboard', 'jobboard_mismatch')""",
            (oid, detail[:60000]),
        )
        queued += 1
    if leads:
        print("\nDiscovery leads (US postings from organizations not in our database):")
        for p in leads:
            print(f"  - {p['org']} | {p['position']} ({p['contract'] or 'terms n/a'}) | {p['location']} | {p['url']}")
    if not dry:
        conn.commit()
    conn.close()
    print(f"\nJob-board check: {len(mismatches)} orchestra(s) with postings we lack; {queued} newly queued; "
          f"{len(leads)} discovery lead(s){' (dry run)' if dry else ''}.")


if __name__ == "__main__":
    main()
