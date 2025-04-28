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

# --- Register New User ---
def create_user(phone, password):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (phone, password) VALUES (?, ?)", (phone, password))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"Error creating user: {e}")
        return False

# --- Authenticate Existing User ---
def authenticate_user(phone, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, phone FROM users WHERE phone = ? AND password = ?", (phone, password))
    user = cursor.fetchone()
    conn.close()
    return user
