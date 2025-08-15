import sqlite3
from datetime import datetime, date

DB_PATH = "inventory.db"

# --- DB Connection ---
def get_connection():
    return sqlite3.connect(DB_PATH)

# --- Create Tables (Users + Inventory + Usage Log) ---
def create_tables():
    conn = get_connection()
    c = conn.cursor()

    # --- Users Table ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL
        )
    ''')

    # --- Inventory Table with full tracking ---
    c.execute('''
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
            last_used_month TEXT DEFAULT '',
            stable INTEGER DEFAULT 0,
            price_per_unit REAL DEFAULT 0.0,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    ''')

    # --- Gentle migrations for inventory ---
    for col, ddl in [
        ("money_lost", "ALTER TABLE inventory ADD COLUMN money_lost REAL DEFAULT 0.0"),
    ]:
        try:
            c.execute(f"SELECT {col} FROM inventory LIMIT 1")
        except sqlite3.OperationalError:
            c.execute(ddl)

    # --- Usage Log Table (we'll enrich it with new columns if missing) ---
    c.execute('''
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id INTEGER,
            used_date TEXT,
            used_count INTEGER
        )
    ''')

    # Upgrade usage_log to carry richer info without nuking old data
    for col, ddl in [
        ("event_type",   "ALTER TABLE usage_log ADD COLUMN event_type TEXT"),
        ("quantity",     "ALTER TABLE usage_log ADD COLUMN quantity REAL"),
        ("unit",         "ALTER TABLE usage_log ADD COLUMN unit TEXT"),
        ("step_count",   "ALTER TABLE usage_log ADD COLUMN step_count INTEGER"),
        ("value_shekel", "ALTER TABLE usage_log ADD COLUMN value_shekel REAL"),
        ("ts",           "ALTER TABLE usage_log ADD COLUMN ts TEXT"),
        ("month_key",    "ALTER TABLE usage_log ADD COLUMN month_key TEXT"),
    ]:
        try:
            c.execute(f"SELECT {col} FROM usage_log LIMIT 1")
        except sqlite3.OperationalError:
            c.execute(ddl)

    conn.commit()
    conn.close()

# ---------- Auth helpers unchanged ----------
def create_user(phone, password, name):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE phone = ?", (phone,))
    if c.fetchone():
        conn.close()
        return False
    try:
        c.execute("INSERT INTO users (phone, password, name) VALUES (?, ?, ?)", (phone, password, name))
        conn.commit()
        return True
    except Exception as e:
        print("❌ Error creating user:", e)
        return False
    finally:
        conn.close()

def authenticate_user(phone, password):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, phone, name FROM users WHERE phone = ? AND password = ?", (phone, password))
    user = c.fetchone()
    conn.close()
    return user

# --- Update Inventory Item ---
def update_item(item_id, name, expiration, food_type, amount, unit, price_per_unit=None):
    conn = get_connection()
    c = conn.cursor()
    if price_per_unit is None:
        c.execute("""
            UPDATE inventory
            SET name = ?, expiration = ?, type = ?, amount = ?, unit = ?
            WHERE id = ?
        """, (name, expiration, food_type, amount, unit, item_id))
    else:
        c.execute("""
            UPDATE inventory
            SET name = ?, expiration = ?, type = ?, amount = ?, unit = ?, price_per_unit = ?
            WHERE id = ?
        """, (name, expiration, food_type, amount, unit, price_per_unit, item_id))
    conn.commit()
    conn.close()

# --- Monthly Reset of used/expired counters ---
def reset_monthly_counters():
    conn = get_connection()
    c = conn.cursor()
    current_month = date.today().strftime("%Y-%m")
    c.execute("SELECT id, last_used_month FROM inventory")
    rows = c.fetchall()
    for item_id, last_month in rows:
        if last_month != current_month:
            c.execute("""
                UPDATE inventory
                SET used_count = 0,
                    expired_count = 0,
                    last_used_month = ?
                WHERE id = ?
            """, (current_month, item_id))
    conn.commit()
    conn.close()

# ---------- Unit math helpers ----------
STEP_GRAMS = 100.0
STEP_ML = 100.0

def _normalize_quantity(qty: float, unit: str):
    """Return (normalized_amount, normalized_unit, step_size). +1 per pc or per 100 g/ml."""
    unit = (unit or "pcs").lower().strip()
    if unit in ("pcs", "pc", "piece"):
        return qty, "pcs", 1.0
    if unit in ("g",):
        return qty, "g", STEP_GRAMS
    if unit in ("kg",):
        return qty * 1000.0, "g", STEP_GRAMS
    if unit in ("ml",):
        return qty, "ml", STEP_ML
    if unit in ("l", "lt", "liter", "litre"):
        return qty * 1000.0, "ml", STEP_ML
    # Unknown circus units default to pieces. Your future self can fight you later.
    return qty, "pcs", 1.0

def _compute_step_count(qty: float, unit: str) -> int:
    amount_norm, _, step_size = _normalize_quantity(qty, unit)
    if step_size <= 0:
        return 0
    # integer ceiling without importing math
    steps = int((amount_norm + step_size - 1) // step_size)
    return max(steps, 0)

def _today_keys():
    ts = datetime.now()
    return ts.isoformat(timespec="seconds"), ts.strftime("%Y-%m")

# ---------- Core operations ----------
def use_item(item_id: int, qty: float):
    """
    Decrease stock by qty, increment used_count by step rule, log the event.
    No money lost for usage because you actually used it like a responsible mammal.
    """
    if qty <= 0:
        raise ValueError("Quantity must be positive.")

    conn = get_connection()
    c = conn.cursor()

    c.execute("SELECT user_id, amount, unit, used_count FROM inventory WHERE id = ?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise ValueError("Item not found.")

    user_id, amount, unit, used_count = row
    amount = amount or 0.0
    if qty > amount:
        conn.close()
        raise ValueError(f"Not enough stock: have {amount} {unit}, asked to use {qty} {unit}.")

    step_inc = _compute_step_count(qty, unit)
    new_amount = amount - qty
    new_used = (used_count or 0) + step_inc

    c.execute("""
        UPDATE inventory
        SET amount = ?, used_count = ?
        WHERE id = ?
    """, (new_amount, new_used, item_id))

    ts, month_key = _today_keys()
    c.execute("""
        INSERT INTO usage_log (user_id, item_id, event_type, quantity, unit, step_count, value_shekel, ts, month_key)
        VALUES (?, ?, 'used', ?, ?, ?, 0.0, ?, ?)
    """, (user_id, item_id, qty, unit, step_inc, ts, month_key))

    conn.commit()
    conn.close()
    return {"used_step_added": step_inc, "remaining": new_amount, "unit": unit}

def expire_item(item_id: int, qty: float | None = None):
    """
    Mark qty as expired (default: entire remaining amount), increment expired_count by step rule,
    add NIS to money_lost (qty × price_per_unit), log it.
    """
    conn = get_connection()
    c = conn.cursor()

    c.execute("""SELECT user_id, amount, unit, price_per_unit, expired_count, money_lost
                 FROM inventory WHERE id = ?""", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise ValueError("Item not found.")

    user_id, amount, unit, ppu, expired_count, money_lost = row
    amount = amount or 0.0
    if qty is None:
        qty = amount
    if qty <= 0:
        conn.close()
        raise ValueError("Quantity must be positive.")
    if qty > amount:
        conn.close()
        raise ValueError(f"Not enough stock to expire: have {amount} {unit}, tried to expire {qty} {unit}.")

    step_inc = _compute_step_count(qty, unit)
    lost_value = round((ppu or 0.0) * qty, 2)

    new_amount = amount - qty
    new_expired = (expired_count or 0) + step_inc
    new_lost = round((money_lost or 0.0) + lost_value, 2)

    c.execute("""
        UPDATE inventory
        SET amount = ?, expired_count = ?, money_lost = ?
        WHERE id = ?
    """, (new_amount, new_expired, new_lost, item_id))

    ts, month_key = _today_keys()
    c.execute("""
        INSERT INTO usage_log (user_id, item_id, event_type, quantity, unit, step_count, value_shekel, ts, month_key)
        VALUES (?, ?, 'expired', ?, ?, ?, ?, ?, ?)
    """, (user_id, item_id, qty, unit, step_inc, lost_value, ts, month_key))

    conn.commit()
    conn.close()
    return {"expired_step_added": step_inc, "lost_nis_total": new_lost, "remaining": new_amount, "unit": unit}

# Convenience: monthly totals for dashboards without pain
def get_monthly_summary(user_id: int, month_key: str | None = None):
    conn = get_connection()
    c = conn.cursor()
    if not month_key:
        _, month_key = _today_keys()
    c.execute("""
        SELECT
            SUM(CASE WHEN event_type='used' THEN step_count ELSE 0 END) AS used_steps,
            SUM(CASE WHEN event_type='expired' THEN step_count ELSE 0 END) AS expired_steps,
            SUM(CASE WHEN event_type='expired' THEN value_shekel ELSE 0 END) AS money_lost
        FROM usage_log
        WHERE user_id = ? AND month_key = ?
    """, (user_id, month_key))
    row = c.fetchone() or (0, 0, 0.0)
    conn.close()
    return {
        "month": month_key,
        "used_steps": int(row[0] or 0),
        "expired_steps": int(row[1] or 0),
        "money_lost": round(row[2] or 0.0, 2)
    }

# Ensure tables exist and migrations run at import
create_tables()
