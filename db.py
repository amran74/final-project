# db.py — cleaned and safe
import sqlite3
from datetime import datetime, date
from typing import Optional, Tuple

DB_PATH = "inventory.db"

# ==============================
# Connection
# ==============================

def get_connection() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.execute("PRAGMA foreign_keys = ON")
    return con

# ==============================
# Safe additive migration helper
# ==============================

def _ensure_column(c: sqlite3.Cursor, table: str, col: str, ddl: str) -> None:
    """
    Add column if missing, using PRAGMA table_info instead of selecting a non-existent column.
    `ddl` must be a full: ALTER TABLE "<table>" ADD COLUMN "<col>" <TYPE ...>
    """
    table_quoted = table.strip().strip('"')
    col_quoted = col.strip().strip('"')
    c.execute(f'PRAGMA table_info("{table_quoted}")')
    existing = {row[1] for row in c.fetchall()}  # row[1] is column name
    if col_quoted not in existing:
        c.execute(ddl)

# ==============================
# Schema / Migrations
# ==============================

def create_tables() -> None:
    """
    Create base tables and apply additive migrations without destroying existing data.
    Order matters: create base, then extend with _ensure_column.
    """
    conn = get_connection()
    c = conn.cursor()

    # --- Users (base) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL
        )
    """)

    # Users extras
    _ensure_column(c, "users", "secret_question",
                   'ALTER TABLE "users" ADD COLUMN "secret_question" TEXT')
    _ensure_column(c, "users", "secret_answer",
                   'ALTER TABLE "users" ADD COLUMN "secret_answer" TEXT')

    # --- Inventory (base) ---
    c.execute("""
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
    """)

    # Inventory extras (additive, safe)
    _ensure_column(c, "inventory", "money_lost",
                   'ALTER TABLE "inventory" ADD COLUMN "money_lost" REAL DEFAULT 0.0')
    _ensure_column(c, "inventory", "frozen_until",
                   'ALTER TABLE "inventory" ADD COLUMN "frozen_until" TEXT')
    _ensure_column(c, "inventory", "perishability",
                   'ALTER TABLE "inventory" ADD COLUMN "perishability" INTEGER DEFAULT 2')

    # --- Usage log (base; legacy compatible) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id INTEGER,
            used_date TEXT,       -- legacy
            used_count INTEGER    -- legacy
        )
    """)

    # Usage_log extras (modern fields; additive, safe)
    _ensure_column(c, "usage_log", "event_type",
                   'ALTER TABLE "usage_log" ADD COLUMN "event_type" TEXT')
    _ensure_column(c, "usage_log", "quantity",
                   'ALTER TABLE "usage_log" ADD COLUMN "quantity" REAL')
    _ensure_column(c, "usage_log", "unit",
                   'ALTER TABLE "usage_log" ADD COLUMN "unit" TEXT')
    _ensure_column(c, "usage_log", "step_count",
                   'ALTER TABLE "usage_log" ADD COLUMN "step_count" INTEGER')
    _ensure_column(c, "usage_log", "value_shekel",
                   'ALTER TABLE "usage_log" ADD COLUMN "value_shekel" REAL')
    _ensure_column(c, "usage_log", "ts",
                   'ALTER TABLE "usage_log" ADD COLUMN "ts" TEXT')
    _ensure_column(c, "usage_log", "month_key",
                   'ALTER TABLE "usage_log" ADD COLUMN "month_key" TEXT')

    # --- Shopping list (base) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS shopping_list (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            item_name TEXT NOT NULL,
            quantity REAL DEFAULT 1,
            unit TEXT DEFAULT 'pcs',
            added_at TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()

# ==============================
# Auth helpers
# ==============================

def create_user(phone: str, password: str, name: str,
                secret_question: str = None, secret_answer: str = None) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE phone = ?", (phone,))
    if c.fetchone():
        conn.close()
        return False
    try:
        c.execute("""
            INSERT INTO users (phone, password, name, secret_question, secret_answer)
            VALUES (?, ?, ?, ?, ?)
        """, (phone, password, name, secret_question, (secret_answer or "").lower()))
        conn.commit()
        return True
    except Exception as e:
        print("❌ Error creating user:", e)
        return False
    finally:
        conn.close()

def authenticate_user(phone: str, password: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, phone, name FROM users WHERE phone = ? AND password = ?", (phone, password))
    user = c.fetchone()
    conn.close()
    return user

def get_user_by_phone(phone: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, phone, name, secret_question, secret_answer
        FROM users WHERE phone = ?
    """, (phone,))
    user = c.fetchone()
    conn.close()
    return user

def update_password_by_phone(phone: str, new_password: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET password = ? WHERE phone = ?", (new_password, phone))
    conn.commit()
    success = c.rowcount > 0
    conn.close()
    return success

# ==============================
# Inventory updates and monthly reset
# ==============================

def update_item(item_id: int, name: str, expiration: str, food_type: str,
                amount: float, unit: str, price_per_unit: Optional[float] = None) -> None:
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

def reset_monthly_counters() -> None:
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

# ==============================
# Unit math
# ==============================

STEP_GRAMS = 100.0
STEP_ML = 100.0

def _normalize_quantity(qty: float, unit: str) -> Tuple[float, str, float]:
    u = (unit or "pcs").lower().strip()
    if u in ("pcs", "pc", "piece"):
        return qty, "pcs", 1.0
    if u == "g":
        return qty, "g", STEP_GRAMS
    if u == "kg":
        return qty * 1000.0, "g", STEP_GRAMS
    if u == "ml":
        return qty, "ml", STEP_ML
    if u in ("l", "lt", "liter", "litre"):
        return qty * 1000.0, "ml", STEP_ML
    return qty, "pcs", 1.0

def _compute_step_count(qty: float, unit: str) -> int:
    amount_norm, _, step_size = _normalize_quantity(qty, unit)
    if step_size <= 0:
        return 0
    return max(int((amount_norm + step_size - 1) // step_size), 0)

def _one_step_qty_in_unit(unit: str) -> float:
    u = (unit or "pcs").lower().strip()
    if u in ("pcs", "pc", "piece"):
        return 1.0
    if u == "g":
        return 100.0
    if u == "kg":
        return 0.1
    if u == "ml":
        return 100.0
    if u in ("l", "lt", "liter", "litre"):
        return 0.1
    return 1.0

def _today_keys() -> Tuple[str, str]:
    ts = datetime.now()
    return ts.isoformat(timespec="seconds"), ts.strftime("%Y-%m")

# ==============================
# Core operations
# ==============================

def use_item(item_id: int, qty: float) -> dict:
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

def expire_item(item_id: int, qty: Optional[float] = None) -> dict:
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

def use_one_step(item_id: int) -> dict:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id, amount, unit, used_count FROM inventory WHERE id = ?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise ValueError("Item not found.")

    user_id, amount, unit, used_count = row
    amount = amount or 0.0
    step_qty = _one_step_qty_in_unit(unit)

    if amount < step_qty:
        conn.close()
        raise ValueError(f"Not enough stock to use one step: have {amount} {unit}, need {step_qty} {unit}.")

    new_amount = amount - step_qty
    new_used = (used_count or 0) + 1

    c.execute("UPDATE inventory SET amount = ?, used_count = ? WHERE id = ?", (new_amount, new_used, item_id))

    ts, month_key = _today_keys()
    c.execute("""
        INSERT INTO usage_log (user_id, item_id, event_type, quantity, unit, step_count, value_shekel, ts, month_key)
        VALUES (?, ?, 'used', ?, ?, 1, 0.0, ?, ?)
    """, (user_id, item_id, step_qty, unit, ts, month_key))

    conn.commit()
    conn.close()
    return {"used_step_added": 1, "deducted": step_qty, "remaining": new_amount, "unit": unit}

def expire_all(item_id: int) -> dict:
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
    if amount <= 0:
        conn.close()
        return {"expired_step_added": 0, "lost_nis_total": float(money_lost or 0.0), "remaining": 0.0, "unit": unit}

    step_inc = _compute_step_count(amount, unit)
    lost_value = round((ppu or 0.0) * amount, 2)

    new_expired = (expired_count or 0) + step_inc
    new_lost = round((money_lost or 0.0) + lost_value, 2)

    c.execute("""
        UPDATE inventory
        SET amount = 0, expired_count = ?, money_lost = ?
        WHERE id = ?
    """, (new_expired, new_lost, item_id))

    ts, month_key = _today_keys()
    c.execute("""
        INSERT INTO usage_log (user_id, item_id, event_type, quantity, unit, step_count, value_shekel, ts, month_key)
        VALUES (?, ?, 'expired', ?, ?, ?, ?, ?, ?)
    """, (user_id, item_id, amount, unit, step_inc, lost_value, ts, month_key))

    conn.commit()
    conn.close()
    return {"expired_step_added": step_inc, "lost_nis_total": new_lost, "remaining": 0.0, "unit": unit}

# ==============================
# Reporting
# ==============================

def get_monthly_summary(user_id: int, month_key: Optional[str] = None) -> dict:
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

# ==============================
# Shopping list helpers
# ==============================

def create_shopping_list_table() -> None:
    # Kept for backward compatibility. Tables are already created in create_tables().
    pass

def add_to_shopping_list(user_id: int, item_name: str, quantity: float = 1, unit: str = "pcs") -> None:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO shopping_list (user_id, item_name, quantity, unit, added_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, item_name, quantity, unit, datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()

def get_shopping_list(user_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id, item_name, quantity, unit, added_at FROM shopping_list WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def remove_from_shopping_list(item_id: int) -> None:
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM shopping_list WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

def clear_shopping_list(user_id: int) -> None:
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM shopping_list WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# Ensure tables exist and migrations run at import time
create_tables()
