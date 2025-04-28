import sqlite3

# --- Database Connection ---
def get_connection():
    return sqlite3.connect("inventory.db")

# --- Create Users Table ---
def create_users_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# --- Create Inventory Table ---
def create_inventory_table():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            expiration DATE NOT NULL,
            type TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()

# --- Add New User ---
def add_user(phone, password):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (phone, password) VALUES (?, ?)", (phone, password))
        conn.commit()
        conn.close()
        return True
    except:
        return False

# --- Authenticate User ---
def authenticate_user(phone, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, phone FROM users WHERE phone = ? AND password = ?", (phone, password))
    user = cursor.fetchone()
    conn.close()
    return user

# --- Inventory Functions ---
def add_item(user_id, name, expiration, food_type):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO inventory (user_id, name, expiration, type) VALUES (?, ?, ?, ?)",
        (user_id, name, expiration, food_type)
    )
    conn.commit()
    conn.close()

def get_user_inventory(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name, expiration, type FROM inventory WHERE user_id = ?",
        (user_id,)
    )
    items = cursor.fetchall()
    conn.close()
    return items

def delete_expired_items(user_id):
    today = date.today().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM inventory WHERE user_id = ? AND expiration < ?",
        (user_id, today)
    )
    conn.commit()
    conn.close()
