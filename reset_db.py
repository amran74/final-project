import os
import sqlite3

DB_FILE = "inventory.db"

# Delete existing DB file if it exists
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
    print("🧹 Existing database removed.")

# Recreate tables with full schema
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()

# Users Table (with name)
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        phone TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        name TEXT NOT NULL
    )
''')

# Inventory Table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        expiration TEXT NOT NULL,
        type TEXT,
        amount REAL DEFAULT 1,
        unit TEXT DEFAULT 'pcs',
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
''')

conn.commit()
conn.close()

print("✅ New database created with correct structure.")
