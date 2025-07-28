import sqlite3
import os

# Remove existing DB
if os.path.exists("inventory.db"):
    os.remove("inventory.db")

# Recreate it with correct schema
conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

# Users table
cursor.execute('''
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    phone TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    name TEXT NOT NULL
)
''')

# Inventory table
cursor.execute('''
CREATE TABLE inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    expiration TEXT NOT NULL,
    type TEXT,
    amount REAL DEFAULT 1,
    unit TEXT DEFAULT 'pcs',
    used_count INTEGER DEFAULT 0,
    expired_count INTEGER DEFAULT 0,
    last_reset_month TEXT DEFAULT '',
    stable INTEGER DEFAULT 0,
    price_per_unit REAL DEFAULT 0.0,
    FOREIGN KEY(user_id) REFERENCES users(id)
)
''')

# Usage log table
cursor.execute('''
CREATE TABLE usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    item_id INTEGER,
    used_date TEXT,
    used_count INTEGER
)
''')

conn.commit()
conn.close()
print("✅ Database reset and rebuilt.")
