# db.py — schema + WAL/timeout hardening and safe defaults for NOT NULL columns

import sqlite3
from datetime import datetime, date
from typing import Optional, Tuple

DB_PATH = "inventory.db"

# ==============================
# Connection
# ==============================

def get_connection() -> sqlite3.Connection:
    """
    Unified connection with WAL + busy_timeout to reduce 'database is locked'.
    """
    con = sqlite3.connect(DB_PATH, timeout=30.0, check_same_thread=False)
    try:
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
        con.execute("PRAGMA busy_timeout = 30000")
        con.execute("PRAGMA temp_store = MEMORY")
    except Exception:
        pass
    return con

# ==============================
# Safe additive migration helper
# ==============================

def _ensure_column(c: sqlite3.Cursor, table: str, col: str, ddl: str) -> None:
    table_quoted = table.strip().strip('"')
    col_quoted = col.strip().strip('"')
    c.execute(f'PRAGMA table_info("{table_quoted}")')
    existing = {row[1] for row in c.fetchall()}
    if col_quoted not in existing:
        c.execute(ddl)

# ==============================
# Schema / Migrations
# ==============================

def create_tables() -> None:
    """
    Create base tables and apply additive migrations without destroying existing data.
    """
    conn = get_connection()
    c = conn.cursor()

    # --- Users (base) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            name TEXT NOT NULL,
            secret_question TEXT,
            secret_answer TEXT
        )
    """)

    # --- Inventory (base) ---
    # Make expiration NOT NULL with a safe default of empty string.
    c.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            expiration TEXT NOT NULL DEFAULT '',
            type TEXT,
            amount REAL DEFAULT 1,
            unit TEXT DEFAULT 'pcs',
            used_count INTEGER DEFAULT 0,
            expired_count INTEGER DEFAULT 0,
            last_used_month TEXT DEFAULT '',
            stable INTEGER DEFAULT 0,
            price_per_unit REAL DEFAULT 0.0,
            money_lost REAL DEFAULT 0.0,
            frozen_until TEXT,
            perishability INTEGER DEFAULT 2,
            kind TEXT DEFAULT 'ingredient',
            base_unit TEXT DEFAULT 'pcs',
            base_amount REAL DEFAULT 0.0,
            total_cost REAL DEFAULT 0.0,
            price_per_base REAL DEFAULT 0.0,
            storage_state TEXT DEFAULT 'fresh',
            frozen_at TEXT,
            thawed_at TEXT,
            frozen_days_accum INTEGER DEFAULT 0,
            thaw_shelf_life_days INTEGER,
            recipe_note TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
    """)

    # Backfill: if any legacy DB has NULL in expiration, coalesce to ''.
    try:
        c.execute("UPDATE inventory SET expiration='' WHERE expiration IS NULL")
    except Exception:
        pass

    # --- Usage log (base; legacy compatible) ---
    c.execute("""
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id INTEGER,
            used_date TEXT,
            used_count INTEGER,
            event_type TEXT,
            quantity REAL,
            unit TEXT,
            step_count INTEGER,
            value_shekel REAL,
            ts TEXT,
            month_key TEXT
        )
    """)

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

def _today_keys():
    ts = datetime.now()
    return ts.isoformat(timespec="seconds"), ts.strftime("%Y-%m")

# ---- price helpers ----

def _effective_price_per_base(c: sqlite3.Cursor, item_id: int) -> Tuple[float, Optional[str]]:
    try:
        c.execute("SELECT price_per_base, base_unit FROM inventory WHERE id=?", (item_id,))
        row = c.fetchone()
        if row:
            ppb, bu = row
            return float(ppb or 0.0), (bu or None)
    except sqlite3.OperationalError:
        pass
    return 0.0, None

def _compute_loss_shekel(c: sqlite3.Cursor, item_id: int, qty: float, unit: str, ppu: float) -> float:
    if (ppu or 0.0) > 0:
        return round((ppu or 0.0) * (qty or 0.0), 2)

    qty_base, qty_base_unit, _ = _normalize_quantity(qty, unit)
    ppb, inv_base_unit = _effective_price_per_base(c, item_id)

    if ppb > 0 and inv_base_unit and inv_base_unit.lower().strip() == qty_base_unit:
        return round(ppb * qty_base, 2)
    return 0.0

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
    new_amount = max(0.0, amount - qty)
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
    lost_value = _compute_loss_shekel(c, item_id, qty, unit, ppu)

    new_amount = max(0.0, amount - qty)
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
    lost_value = _compute_loss_shekel(c, item_id, amount, unit, ppu)

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
# Monthly reset (App.py imports this)
# ==============================

def reset_monthly_counters() -> None:
    """
    If an item's last_used_month != current month, zero used_count and expired_count,
    then stamp last_used_month to current month. Runs once at app start.
    """
    conn = get_connection()
    c = conn.cursor()
    current_month = date.today().strftime("%Y-%m")
    c.execute("SELECT id, last_used_month FROM inventory")
    rows = c.fetchall()
    for item_id, last_month in rows:
        if (last_month or "") != current_month:
            c.execute("""
                UPDATE inventory
                SET used_count = 0,
                    expired_count = 0,
                    last_used_month = ?
                WHERE id = ?
            """, (current_month, item_id))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    create_tables()
