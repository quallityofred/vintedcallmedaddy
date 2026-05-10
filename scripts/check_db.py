import sqlite3
from pathlib import Path

db_files = ['data/vinted.db', 'data/runtime-check.db', 'data/runtime-check-2.db']

for db_file in db_files:
    path = Path(db_file)
    if not path.exists():
        print(f"{db_file} does not exist")
        continue
    
    print(f"Checking {db_file}...")
    try:
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"  Tables: {tables}")
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table[0]};")
            count = cursor.fetchone()[0]
            print(f"    {table[0]}: {count} records")
        conn.close()
    except Exception as e:
        print(f"  Error: {e}")
