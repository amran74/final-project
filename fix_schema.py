import sqlite3

conn = sqlite3.connect("inventory.db")
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE inventory ADD COLUMN used_count INTEGER DEFAULT 0")
except Exception as e:
    print("used_count:", e)

try:
    cursor.execute("ALTER TABLE inventory ADD COLUMN expired_count INTEGER DEFAULT 0")
except Exception as e:
    print("expired_count:", e)

try:
    cursor.execute("ALTER TABLE inventory ADD COLUMN last_reset_month TEXT DEFAULT ''")
except Exception as e:
    print("last_reset_month:", e)

try:
    cursor.execute("ALTER TABLE inventory ADD COLUMN stable INTEGER DEFAULT 0")
except Exception as e:
    print("stable:", e)

conn.commit()
conn.close()
print("✅ All missing columns added.")
