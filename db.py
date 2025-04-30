import sqlite3

# --- DB Connection ---
def get_connection():
    return sqlite3.connect("inventory.db")

# --- Create Tables (Users + Inventory) ---
def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    # Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
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

# --- Create User ---
def create_user(phone, password):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (phone, password) VALUES (?, ?)", (phone, password))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

# --- Authenticate User ---
def authenticate_user(phone, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, phone FROM users WHERE phone = ? AND password = ?", (phone, password))
    user = cursor.fetchone()
    conn.close()
    return user

# --- Update Inventory Item ---
def update_item(item_id, name, expiration, food_type, amount, unit):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE inventory
        SET name = ?, expiration = ?, type = ?, amount = ?, unit = ?
        WHERE id = ?
    ''', (name, expiration, food_type, amount, unit, item_id))
    conn.commit()
    conn.close()
