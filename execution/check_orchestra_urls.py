"""
Cheap first-pass link checker: does an HTTP HEAD/GET against every stored
orchestras.url and reports non-200 responses. This is meant to run BEFORE
spinning up a full 3-agent state audit, so agents don't have to rediscover
already-broken URLs one at a time (this happened repeatedly this session --
Vermont Symphony, Utah Symphony, Madison Symphony, Loudoun Symphony, Vancouver
Symphony, Wisconsin Chamber Orchestra, etc. were all found broken by agents
that had to stumble into the 404 mid-audit).

A non-200 here is NOT proof of a dead org -- some sites block bare HEAD/GET
requests (Cloudflare, bot-detection) even though the page loads fine in a
real browser. Treat anything flagged here as "needs a live browser check",
per the directive's Section 2C broken-URL workflow -- not an automatic purge.

Usage:
    python execution/check_orchestra_urls.py                 # check all orchestras
    python execution/check_orchestra_urls.py --state Wyoming  # check one state only
"""
import os
import sys
import time
import mysql.connector
import requests
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
}

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
}


def check_urls(state_filter=None, timeout=10):
    conn = mysql.connector.connect(**CONFIG)
    cur = conn.cursor(dictionary=True)
    if state_filter:
        cur.execute("SELECT id, name, state, url FROM orchestras WHERE state = %s ORDER BY name", (state_filter,))
    else:
        cur.execute("SELECT id, name, state, url FROM orchestras ORDER BY state, name")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    print(f"Checking {len(rows)} orchestra URL(s)...\n")
    broken = []
    for r in rows:
        url = r['url']
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            status = resp.status_code
        except requests.exceptions.RequestException as e:
            status = f"ERROR: {type(e).__name__}"

        ok = isinstance(status, int) and 200 <= status < 400
        marker = "OK  " if ok else "FLAG"
        print(f"  [{marker}] [{r['id']}] {r['name']} ({r['state']}) -> {status}  {url}")
        if not ok:
            broken.append((r['id'], r['name'], r['state'], url, status))
        time.sleep(0.3)  # be polite

    print(f"\n{len(broken)} flagged for a live-browser re-check (per directive Section 2C):")
    for b in broken:
        print(f"  [{b[0]}] {b[1]} ({b[2]}) -> {b[4]}  {b[3]}")

    return broken


if __name__ == "__main__":
    state = None
    if "--state" in sys.argv:
        state = sys.argv[sys.argv.index("--state") + 1]
    check_urls(state_filter=state)
