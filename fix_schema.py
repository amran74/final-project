import sqlite3

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE inventory ADD COLUMN used_count INTEGER DEFAULT 0")
except:
    print("used_count already exists")

try:
    cursor.execute("ALTER TABLE inventory ADD COLUMN expired_count INTEGER DEFAULT 0")
except:
    print("expired_count already exists")

try:
    cursor.execute("ALTER TABLE inventory ADD COLUMN last_reset_month TEXT DEFAULT ''")
except:
    print("last_reset_month already exists")

try:
    cursor.execute("ALTER TABLE inventory ADD COLUMN stable INTEGER DEFAULT 0")
except:
    print("stable already exists")

conn.commit()
conn.close()

print("✅ Schema fixed successfully")
