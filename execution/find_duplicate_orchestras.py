"""
Finds likely duplicate orchestra records -- the same real-world organization
stored twice under slightly different names/spellings/URLs. This has been a
recurring, previously-manual discovery this session (Seattle Symphony,
Philadelphia Orchestra, NEPA Philharmonic, South Dakota Symphony, Tulsa
Symphony, Santa Fe Symphony, several Texas orchestras, Tacoma City Symphony).

Three detection passes:
  1. Exact match on normalized name (lowercased/trimmed) + state
  2. Same normalized URL (scheme/www/trailing-slash stripped) across two rows
  3. High name-similarity (difflib ratio) within the same state, to catch
     typos/spelling drift (e.g. "Seatle Symphony Orchestra" vs "Seattle
     Symphony")

This is a candidate list, not an auto-merge -- a human/agent should verify
each flagged pair actually represents one organization before merging.

Usage:
    python execution/find_duplicate_orchestras.py
    python execution/find_duplicate_orchestras.py --threshold 0.85   # tune fuzzy match sensitivity
"""
import os
import re
import sys
import difflib
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
}


def normalize_url(url):
    if not url:
        return ""
    u = url.lower().strip()
    u = re.sub(r'^https?://', '', u)
    u = re.sub(r'^www\.', '', u)
    u = u.rstrip('/')
    return u


def find_duplicates(threshold=0.88):
    conn = mysql.connector.connect(**CONFIG)
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT id, name, city, state, url FROM orchestras")
    rows = cur.fetchall()

    print(f"Scanned {len(rows)} orchestras.\n")

    # 1. Exact normalized name + state
    print("--- EXACT NAME MATCHES (same normalized name + state) ---")
    seen = {}
    for r in rows:
        key = (re.sub(r'\s+', ' ', r['name']).strip().lower(), r['state'])
        seen.setdefault(key, []).append(r)
    for key, group in seen.items():
        if len(group) > 1:
            print(f"  {key[0]!r} in {key[1]}: {[(g['id'], g['name']) for g in group]}")

    # 2. Same normalized URL
    print("\n--- SAME URL (different rows pointing at the same site) ---")
    by_url = {}
    for r in rows:
        nu = normalize_url(r['url'])
        if not nu:
            continue
        by_url.setdefault(nu, []).append(r)
    for nu, group in by_url.items():
        if len(group) > 1:
            print(f"  {nu!r}: {[(g['id'], g['name'], g['state']) for g in group]}")

    # 3. Fuzzy name similarity within the same state
    print(f"\n--- FUZZY NAME MATCHES (same state, similarity >= {threshold}) ---")
    by_state = {}
    for r in rows:
        by_state.setdefault(r['state'], []).append(r)
    flagged = set()
    for state, group in by_state.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                ratio = difflib.SequenceMatcher(None, a['name'].lower(), b['name'].lower()).ratio()
                if ratio >= threshold and a['name'].lower() != b['name'].lower():
                    pair = tuple(sorted([a['id'], b['id']]))
                    if pair in flagged:
                        continue
                    flagged.add(pair)
                    print(f"  ({ratio:.2f}) [{a['id']}] {a['name']!r} <-> [{b['id']}] {b['name']!r} ({state})")

    cur.close()
    conn.close()


if __name__ == "__main__":
    t = 0.88
    if "--threshold" in sys.argv:
        t = float(sys.argv[sys.argv.index("--threshold") + 1])
    find_duplicates(threshold=t)
