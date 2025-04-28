import sqlite3

# Connect to database
def get_connection():
    return sqlite3.connect("inventory.db")

# Create new user
def create_user(phone, password):
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (phone, password) VALUES (?, ?)", (phone, password))
        conn.commit()
        conn.close()
        return True
    except:
        return False

# Authenticate user
def authenticate_user(phone, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, phone FROM users WHERE phone = ? AND password = ?", (phone, password))
    user = cursor.fetchone()
    conn.close()
    return user
