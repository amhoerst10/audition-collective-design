"""
Finds audition records where every relevant date field (final_audition, or
preliminary_audition if final_audition is null) has already passed.

This is the PURGE-candidate query per AUDITION_CAPTURE.md's staleness rule:
placeholder rows ("No auditions reported at this time", all dates NULL) are
never flagged here -- only real postings whose audition round has concluded.

Per directive, a live-page re-check is still recommended before purging (a
listing could have been quietly extended), but this script's output is a
reliable first-pass candidate list rather than a guaranteed purge order.

Usage:
    python execution/find_expired_auditions.py            # list candidates
    python execution/find_expired_auditions.py --purge     # list AND delete them
"""
import os
import sys
import mysql.connector
from dotenv import load_dotenv

load_dotenv()

CONFIG = {
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST'),
    'database': os.getenv('DB_NAME'),
}

QUERY = """
    SELECT a.id, o.name, o.state, a.position, a.instrumentation,
           a.application_deadline, a.preliminary_audition, a.final_audition
    FROM auditions a
    JOIN orchestras o ON o.id = a.orchestra_id
    WHERE
      (a.final_audition IS NOT NULL AND a.final_audition < CURDATE())
      OR (a.final_audition IS NULL AND a.preliminary_audition IS NOT NULL
          AND a.preliminary_audition < CURDATE())
    ORDER BY o.state, o.name
"""


def find_expired(do_purge=False):
    conn = mysql.connector.connect(**CONFIG)
    cur = conn.cursor()
    cur.execute(QUERY)
    rows = cur.fetchall()

    print(f"Found {len(rows)} expired audition record(s):\n")
    for r in rows:
        aid, org, state, pos, instr, deadline, prelim, final = r
        print(f"  [{aid}] {org} ({state}) - {pos} ({instr}) "
              f"| deadline={deadline} prelim={prelim} final={final}")

    if do_purge and rows:
        ids = [r[0] for r in rows]
        fmt = ','.join(['%s'] * len(ids))
        cur.execute(f"DELETE FROM auditions WHERE id IN ({fmt})", ids)
        conn.commit()
        print(f"\nPurged {cur.rowcount} record(s).")
    elif do_purge:
        print("\nNothing to purge.")
    else:
        print("\n(dry run -- pass --purge to delete these records)")

    cur.close()
    conn.close()
    return rows


if __name__ == "__main__":
    find_expired(do_purge="--purge" in sys.argv)
