"""
Seed sort_cache.db with sample data for the MVP demo.
In production, this data comes from your Google Sheet via sync_sheet.py.
"""
import sqlite3, os
from datetime import datetime

DB_PATH = os.environ.get('DB_PATH', 'sort_cache.db')
now = datetime.utcnow().isoformat()

conn = sqlite3.connect(DB_PATH)
conn.executescript("""
DROP TABLE IF EXISTS sort_master;
DROP TABLE IF EXISTS keyword_map;
DROP TABLE IF EXISTS sync_log;
DROP TABLE IF EXISTS scan_log;

CREATE TABLE sort_master (
    pincode TEXT PRIMARY KEY, city TEXT, area_name TEXT NOT NULL,
    level1 TEXT, level2 TEXT, level3 TEXT,
    sort_code TEXT NOT NULL, rider_zone TEXT, active INTEGER DEFAULT 1,
    notes TEXT, synced_at TEXT
);

CREATE TABLE keyword_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword TEXT NOT NULL, pincode TEXT NOT NULL,
    priority INTEGER DEFAULT 99, active INTEGER DEFAULT 1, synced_at TEXT
);

CREATE TABLE sync_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    synced_at TEXT NOT NULL, pincodes_loaded INTEGER, keywords_loaded INTEGER,
    status TEXT, error TEXT
);

CREATE TABLE scan_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scanned_at TEXT NOT NULL, shipment_id TEXT NOT NULL, address TEXT,
    pincode TEXT, sort_code TEXT, rider_zone TEXT,
    match_method TEXT, confidence INTEGER, latency_ms INTEGER
);
""")

# Sample sort master (mirrors what your Google Sheet would have)
master = [
    ('110001', 'Delhi',     'Connaught Place',  '1', 'A', '01', '1A01', 'North R1', 1, 'High density'),
    ('110002', 'Delhi',     'Civil Lines',      '1', 'A', '02', '1A02', 'North R1', 1, ''),
    ('110005', 'Delhi',     'Karol Bagh',       '1', 'B', '01', '1B01', 'North R2', 1, ''),
    ('400001', 'Mumbai',    'Fort',             '2', 'A', '01', '2A01', 'South R1', 1, ''),
    ('400050', 'Mumbai',    'Bandra West',      '2', 'B', '01', '2B01', 'West R1',  1, ''),
    ('560034', 'Bangalore', 'Koramangala',      '3', 'A', '01', '3A01', 'East R1',  1, ''),
    ('560001', 'Bangalore', 'MG Road',          '3', 'A', '02', '3A02', 'East R1',  1, ''),
]
conn.executemany(
    """INSERT INTO sort_master
       (pincode, city, area_name, level1, level2, level3, sort_code,
        rider_zone, active, notes, synced_at)
       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
    [(*row, now) for row in master]
)

# Keyword map for fuzzy/abbreviation matches
keywords = [
    ('connaught', '110001', 1),
    ('cp',        '110001', 2),
    ('rajiv chowk', '110001', 3),    # metro station name for Connaught Place
    ('civil lines','110002', 1),
    ('karol bagh','110005', 1),
    ('fort',      '400001', 1),
    ('bandra',    '400050', 1),
    ('koramangala','560034', 1),
    ('koramangla', '560034', 2),     # common misspelling
    ('mg road',   '560001', 1),
    ('victoria terminus', '400001', 3),  # landmark near Fort area
]
conn.executemany(
    "INSERT INTO keyword_map (keyword, pincode, priority, active, synced_at) VALUES (?,?,?,1,?)",
    [(*kw, now) for kw in keywords]
)

conn.execute(
    "INSERT INTO sync_log (synced_at, pincodes_loaded, keywords_loaded, status) VALUES (?,?,?,?)",
    (now, len(master), len(keywords), 'success')
)
conn.commit()
print(f'✓ Seeded {len(master)} pincodes, {len(keywords)} keywords')
conn.close()
