import sqlite3
from datetime import date

# --- DB Connection ---
def get_connection():
    return sqlite3.connect("inventory.db")

# --- Create Tables (Users + Inventory + Usage Log) ---
def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    # --- Users Table ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL
        )
    ''')

    # --- Inventory Table with usage & expiry tracking ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
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
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    # --- Optional: Usage log for future analytics ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id INTEGER,
            used_date TEXT,
            used_count INTEGER
        )
    ''')

    conn.commit()
    conn.close()

# --- Create User (with existence check) ---
def create_user(phone, password, name):
    conn = get_connection()
    cursor = conn.cursor()

    # Check if user exists
    cursor.execute("SELECT id FROM users WHERE phone = ?", (phone,))
    if cursor.fetchone():
        conn.close()
        return False

    try:
        cursor.execute("INSERT INTO users (phone, password, name) VALUES (?, ?, ?)", (phone, password, name))
        conn.commit()
        return True
    except Exception as e:
        print("❌ Error creating user:", e)
        return False
    finally:
        conn.close()

# --- Authenticate User ---
def authenticate_user(phone, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, phone, name FROM users WHERE phone = ? AND password = ?", (phone, password))
    user = cursor.fetchone()
    conn.close()
    return user

# --- Update Inventory Item ---
def update_item(item_id, name, expiration, food_type, amount, unit):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE inventory
        SET name = ?, expiration = ?, type = ?, amount = ?, unit = ?
        WHERE id = ?
    """, (name, expiration, food_type, amount, unit, item_id))
    conn.commit()
    conn.close()

# --- Monthly Reset of used/expired counters ---
def reset_monthly_counters():
    conn = get_connection()
    cursor = conn.cursor()

    current_month = date.today().strftime("%Y-%m")

    cursor.execute("SELECT id, last_reset_month FROM inventory")
    rows = cursor.fetchall()

    for item_id, last_month in rows:
        if last_month != current_month:
            cursor.execute("""
                UPDATE inventory
                SET used_count = 0,
                    expired_count = 0,
                    last_reset_month = ?
                WHERE id = ?
            """, (current_month, item_id))

    conn.commit()
    conn.close()

# --- Ensure tables are created on import ---
create_tables()
