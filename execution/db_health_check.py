import os
import mysql.connector
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

def db_health_check():
    db = mysql.connector.connect(
        host=os.getenv('DB_HOST'),
        user=os.getenv('DB_USER'),
        password=os.getenv('DB_PASSWORD'),
        database=os.getenv('DB_NAME')
    )
    cursor = db.cursor()

    print("--- 1. Duplicate Check (Orchestra ID + Position) ---")
    cursor.execute("""
        SELECT orchestra_id, position, COUNT(*) 
        FROM auditions 
        GROUP BY orchestra_id, position 
        HAVING COUNT(*) > 1
    """)
    dupes = cursor.fetchall()
    if dupes:
        for d in dupes:
            print(f"DUPE: Orch {d[0]}, Pos '{d[1]}', Count {d[2]}")
    else:
        print("No exact duplicates found.")

    print("\n--- 2. Multiple Instrument Check (contains 'or', '/', '&') ---")
    # Exclusion: '(Video / Audio Submission)' is fine
    cursor.execute("""
        SELECT id, orchestra_id, position 
        FROM auditions 
        WHERE (position LIKE '% or %' OR position LIKE '%/%' OR position LIKE '%&%')
        AND position NOT LIKE '%Video / Audio Submission%'
        AND position NOT LIKE '%Contact to Schedule Live%'
    """)
    multis = cursor.fetchall()
    if multis:
        for m in multis:
            print(f"MULTI-INST: ID {m[0]}, Orch {m[1]}, Pos '{m[2]}'")
    else:
        print("No multiple instrument violations found.")

    print("\n--- 3. Non-Position Word Check (Fellowship, Season, etc.) ---")
    non_pos_words = ["Fellowship", "Season", "Program"]
    for word in non_pos_words:
        cursor.execute(f"SELECT id, orchestra_id, position FROM auditions WHERE position LIKE '%{word}%'")
        matches = cursor.fetchall()
        if matches:
            for match in matches:
                print(f"NON-POS WORD '{word}': ID {match[0]}, Orch {match[1]}, Pos '{match[2]}'")
    
    print("\n--- 4. Outdated Records Check (Before Today: 2026-04-22) ---")
    today = "2026-04-22"
    cursor.execute(f"""
        SELECT id, orchestra_id, position, application_deadline, preliminary_audition 
        FROM auditions 
        WHERE (application_deadline < '{today}') 
        OR (preliminary_audition < '{today}')
    """)
    outdated = cursor.fetchall()
    if outdated:
        for o in outdated:
            print(f"OUTDATED: ID {o[0]}, Orch {o[1]}, Pos '{o[2]}', Deadline {o[3]}, Prelim {o[4]}")
    else:
        print("No outdated records found.")

    cursor.close()
    db.close()

if __name__ == "__main__":
    db_health_check()
