# inventory_core.py — Inventory domain logic (no Streamlit UI)
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Tuple, List, Dict, Any

from db import get_connection, create_tables, _today_keys, _compute_step_count

# ---------------------------------
# Units and conversions
# ---------------------------------
UNITS = ["pcs", "g", "kg", "mg", "ml", "l"]
BASE_FOR = {"pcs": "pcs", "g": "g", "kg": "g", "mg": "g", "ml": "ml", "l": "ml"}
MULT_TO_BASE = {"pcs": 1.0, "mg": 0.001, "g": 1.0, "kg": 1000.0, "ml": 1.0, "l": 1000.0}

CATEGORIES = [
    "Vegetable", "Fruit", "Dairy", "Meat", "Fish", "Bakery", "Pantry",
    "Frozen", "Snacks", "Beverages", "Household", "Other"
]

FAR_FUTURE = date(2099, 12, 31)

# ---------------------------------
# Migrations (idempotent)
# ---------------------------------
MIGRATIONS = [
    ("ALTER TABLE inventory ADD COLUMN kind TEXT DEFAULT 'ingredient'",),
    ("ALTER TABLE inventory ADD COLUMN base_unit TEXT DEFAULT 'pcs'",),
    ("ALTER TABLE inventory ADD COLUMN base_amount REAL DEFAULT 0.0",),
    ("ALTER TABLE inventory ADD COLUMN total_cost REAL DEFAULT 0.0",),
    ("ALTER TABLE inventory ADD COLUMN price_per_base REAL DEFAULT 0.0",),
    ("ALTER TABLE inventory ADD COLUMN storage_state TEXT DEFAULT 'fresh'",),
    ("ALTER TABLE inventory ADD COLUMN frozen_at TEXT",),
    ("ALTER TABLE inventory ADD COLUMN thawed_at TEXT",),
    ("ALTER TABLE inventory ADD COLUMN frozen_days_accum INTEGER DEFAULT 0",),
    ("ALTER TABLE inventory ADD COLUMN thaw_shelf_life_days INTEGER",),
    ("ALTER TABLE inventory ADD COLUMN recipe_note TEXT",),
    ("ALTER TABLE inventory ADD COLUMN money_lost REAL DEFAULT 0.0",),
    ("ALTER TABLE inventory ADD COLUMN expired_count INTEGER DEFAULT 0",),
    ("CREATE TABLE IF NOT EXISTS recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, prepared_item_id INTEGER NOT NULL UNIQUE)",),
    ("CREATE TABLE IF NOT EXISTS recipe_components (id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id INTEGER NOT NULL, ingredient_item_id INTEGER NOT NULL, quantity_base REAL NOT NULL, UNIQUE(recipe_id, ingredient_item_id))",),
    ("CREATE TABLE IF NOT EXISTS batches (id INTEGER PRIMARY KEY AUTOINCREMENT, prepared_item_id INTEGER NOT NULL, cooked_at TEXT NOT NULL, total_yield_base REAL NOT NULL, portion_size_base REAL NOT NULL, remaining_base REAL NOT NULL, expiration TEXT, storage_state TEXT DEFAULT 'fresh', frozen_at TEXT, thawed_at TEXT, frozen_days_accum INTEGER DEFAULT 0, batch_cost REAL)",),
]

def run_migrations():
    create_tables()
    conn = get_connection(); c = conn.cursor()
    c.execute("PRAGMA table_info(inventory)")
    cols = {row[1] for row in c.fetchall()}
    for mig in MIGRATIONS:
        stmt = mig[0]
        if stmt.startswith("CREATE TABLE"):
            try: c.execute(stmt); conn.commit()
            except Exception: pass
            continue
        target_col = stmt.split(" ADD COLUMN ")[1].split(" ")[0]
        if target_col not in cols:
            try: c.execute(stmt); conn.commit(); cols.add(target_col)
            except Exception: pass
    conn.close()

# ---------------------------------
# Helpers
# ---------------------------------
def parse_iso(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()

def today() -> date:
    return date.today()

def iso_today() -> str:
    return today().strftime("%Y-%m-%d")

def to_base(amount: float, unit: str) -> Tuple[float, str]:
    unit = (unit or "pcs").lower()
    if unit not in BASE_FOR: return amount, "pcs"
    return float(amount) * MULT_TO_BASE[unit], BASE_FOR[unit]

def from_base(amount_base: float, ui_unit: str) -> float:
    u = (ui_unit or "pcs").lower()
    if u == "kg": return amount_base / 1000.0
    if u == "g":  return amount_base
    if u == "mg": return amount_base * 1000.0
    if u == "l":  return amount_base / 1000.0
    if u == "ml": return amount_base
    return amount_base  # pcs

def compute_price_per_base(total_cost: float, base_amount: float) -> float:
    return 0.0 if float(base_amount or 0) <= 0 else float(total_cost or 0.0) / float(base_amount)

def _ppu_to_price_per_base(ppu: float, unit: str, base_unit: str) -> float:
    if not ppu or ppu <= 0: return 0.0
    unit = (unit or "").lower()
    if base_unit == "g":
        if unit == "kg": return ppu / 1000.0
        if unit == "g":  return ppu
        if unit == "mg": return ppu * 1000.0
        return 0.0
    if base_unit == "ml":
        if unit in ("l", "lt", "liter", "litre"): return ppu / 1000.0
        if unit == "ml": return ppu
        return 0.0
    return ppu  # pcs

def effective_price_per_base(price_per_base: float, price_per_unit: float, unit: str, base_unit: str) -> float:
    return float(price_per_base or 0.0) if (price_per_base or 0) > 0 else _ppu_to_price_per_base(float(price_per_unit or 0.0), unit, base_unit)

def is_stable_zero(stable: bool, base_amount: float) -> bool:
    try:
        return bool(stable) and float(base_amount or 0.0) <= 0.0
    except Exception:
        return False

# ---------------------------------
# Name→amount auto-parser
# ---------------------------------
# Supported patterns at end of name:
#   "12 pack", "12pcs", "12 pc", "x12", "12x", "500g", "1kg", "2l", "300ml"
_NAME_QTY_PATTERNS = [
    r"(.*)\b(\d+)\s*(?:pack|pcs?|x)\s*$",
    r"(.*)\b(\d+)\s*[xX]\s*$",
    r"(.*)\b(\d+)\s*(pcs?)\s*$",
    r"(.*)\b(\d+(?:\.\d+)?)\s*(mg|g|kg|ml|l)\s*$",
]

def normalize_name_and_amount(name: str, amount_ui: float, unit_ui: str) -> Tuple[str, float, str]:
    base_name = (name or "").strip()
    if not base_name:
        return name, amount_ui, unit_ui
    for pat in _NAME_QTY_PATTERNS:
        m = re.match(pat, base_name, flags=re.IGNORECASE)
        if not m: 
            continue
        item = m.group(1).strip()
        val = m.group(2)
        # unit group may exist
        unit = m.group(3).lower() if len(m.groups()) >= 3 and m.group(3) else None
        try:
            qty = float(val)
        except Exception:
            continue
        if unit in ("mg","g","kg","ml","l"):
            # treat this as amount/unit
            return item, qty, unit
        # otherwise it's pieces
        return item, qty, "pcs"
    return base_name, amount_ui, unit_ui

# ---------------------------------
# Expiration with frozen pause
# ---------------------------------
def effective_expiration(expiration: str, storage_state: str, frozen_at: Optional[str], thawed_at: Optional[str], frozen_days_accum: int) -> date:
    base_exp = parse_iso(expiration)
    paused_days = int(frozen_days_accum or 0)
    if storage_state == "frozen" and frozen_at:
        try:
            paused_days += (today() - parse_iso(frozen_at)).days
        except Exception:
            pass
    return base_exp + timedelta(days=max(0, paused_days))

def status_badge(eff_exp: date, storage_state: str) -> Tuple[str, str]:
    if storage_state == "frozen":
        return "Frozen", "#33BFFF"
    delta = (eff_exp - today()).days
    if delta < 0:  return "Expired", "#FF4B4B"
    if delta <= 2: return "Expiring Soon", "#FFA500"
    return "Fresh", "#4CAF50"

# ---------------------------------
# Data access (core)
# ---------------------------------
def add_item(user_id: int, name: str, expiration: str, food_type: str,
             ui_amount: float, ui_unit: str, total_cost: float,
             kind: str, stable: bool, recipe_note: Optional[str],
             thaw_shelf_life_days: Optional[int], auto_parse: bool = True):
    nm, amt, u = (normalize_name_and_amount(name, ui_amount, ui_unit) if auto_parse else (name, ui_amount, ui_unit))
    base_amount, base_unit = to_base(amt, u)
    price_per_base = compute_price_per_base(total_cost, base_amount)
    exp_to_store = (FAR_FUTURE if is_stable_zero(stable, base_amount) else parse_iso(expiration)).strftime("%Y-%m-%d")
    conn = get_connection(); c = conn.cursor()
    c.execute("""
        INSERT INTO inventory
        (user_id, name, expiration, type, amount, unit, used_count, last_used_month, stable,
         price_per_unit, expired_count, money_lost,
         kind, base_unit, base_amount, total_cost, price_per_base,
         storage_state, frozen_at, thawed_at, frozen_days_accum, thaw_shelf_life_days, recipe_note)
        VALUES (?, ?, ?, ?, ?, ?, 0, strftime('%Y-%m','now'), ?, 0.0, 0, 0.0,
                ?, ?, ?, ?, ?, 'fresh', NULL, NULL, 0, ?, ?)
    """, (user_id, nm, exp_to_store, food_type, amt, u, int(stable),
          kind, base_unit, base_amount, total_cost, price_per_base, thaw_shelf_life_days, recipe_note))
    conn.commit(); conn.close()

def get_user_items(user_id: int) -> List[tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
        SELECT id, name, expiration, type, amount, unit, used_count, last_used_month, stable,
               price_per_unit, COALESCE(expired_count,0), COALESCE(money_lost,0.0),
               kind, base_unit, base_amount, total_cost, price_per_base,
               storage_state, frozen_at, thawed_at, COALESCE(frozen_days_accum,0),
               thaw_shelf_life_days, recipe_note
        FROM inventory
        WHERE user_id=?
        ORDER BY date(expiration) ASC, name ASC
    """, (user_id,))
    rows = c.fetchall(); conn.close()
    return rows

def delete_item(item_id: int):
    conn = get_connection(); conn.execute("DELETE FROM inventory WHERE id=?", (item_id,)); conn.commit(); conn.close()

def update_item(item_id: int, name: str, expiration: str, food_type: str,
                ui_amount: float, ui_unit: str, total_cost: float,
                kind: str, thaw_shelf_life_days: Optional[int], recipe_note: Optional[str],
                stable_flag: Optional[bool] = None, auto_parse: bool = True):
    nm, amt, u = (normalize_name_and_amount(name, ui_amount, ui_unit) if auto_parse else (name, ui_amount, ui_unit))
    base_amount, base_unit = to_base(amt, u)
    price_per_base = compute_price_per_base(total_cost, base_amount)
    conn = get_connection(); c = conn.cursor()
    # figure stable
    if stable_flag is None:
        c.execute("SELECT COALESCE(stable,0) FROM inventory WHERE id=?", (item_id,))
        current_stable = bool((c.fetchone() or [0])[0])
    else:
        current_stable = bool(stable_flag)
    exp_to_store = (FAR_FUTURE if is_stable_zero(current_stable, base_amount) else parse_iso(expiration)).strftime("%Y-%m-%d")
    c.execute("""
        UPDATE inventory
        SET name=?, expiration=?, type=?, amount=?, unit=?, total_cost=?, price_per_base=?,
            base_amount=?, base_unit=?, kind=?, thaw_shelf_life_days=?, recipe_note=?
        WHERE id=?
    """, (nm, exp_to_store, food_type, amt, u, total_cost, price_per_base,
          base_amount, base_unit, kind, thaw_shelf_life_days, recipe_note, item_id))
    # auto-delete depleted non-stable
    if float(base_amount or 0.0) <= 0.0 and not current_stable:
        c.execute("DELETE FROM inventory WHERE id=?", (item_id,))
    conn.commit(); conn.close()

def _log_usage(user_id: int, item_id: int, event: str, qty_ui: float, unit_ui: str, step_inc: int, value_shekel: float):
    ts, month_key = _today_keys()
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      INSERT INTO usage_log (user_id, item_id, event_type, quantity, unit, step_count, value_shekel, ts, month_key)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, item_id, event, float(qty_ui), unit_ui, int(step_inc), float(value_shekel), ts, month_key))
    conn.commit(); conn.close()

def use_quantity(item_id: int, qty_ui: float, ui_unit: str) -> Tuple[bool, str]:
    base_qty, base_u = to_base(qty_ui, ui_unit)
    if base_qty <= 0: return False, "Quantity must be positive"
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT base_amount, storage_state, user_id, unit, COALESCE(stable,0) FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row: conn.close(); return False, "Item not found"
    base_amount, storage_state, user_id, unit_row, stable_flag = row
    if storage_state == "frozen": conn.close(); return False, "Cannot use while frozen. Thaw first."
    if base_qty > float(base_amount or 0): conn.close(); return False, "Not enough on hand"
    new_amount = float(base_amount) - base_qty
    step_inc = _compute_step_count(qty_ui, ui_unit)
    c.execute("""
        UPDATE inventory
        SET base_amount=?, used_count=COALESCE(used_count,0)+?, last_used_month=strftime('%Y-%m','now')
        WHERE id=?
    """, (new_amount, int(step_inc), item_id))
    conn.commit(); conn.close()
    _log_usage(user_id, item_id, "used", qty_ui, (unit_row or ui_unit), step_inc, 0.0)
    # auto delete if depleted and not stable
    if new_amount <= 0 and int(stable_flag or 0) == 0:
        delete_item(item_id)
        return True, f"Used {qty_ui} {ui_unit}. Item removed (depleted)."
    return True, f"Used {qty_ui} {ui_unit}"

def expire_quantity(item_id: int, qty_ui: float, ui_unit: str) -> Tuple[bool, str]:
    base_qty, _ = to_base(qty_ui, ui_unit)
    if base_qty <= 0: return False, "Quantity must be positive"
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT user_id, base_amount, price_per_base, unit, price_per_unit, base_unit, COALESCE(stable,0)
      FROM inventory WHERE id=?
    """, (item_id,))
    row = c.fetchone()
    if not row: conn.close(); return False, "Item not found"
    user_id, base_amount, price_per_base, unit_row, ppu_legacy, base_unit, stable_flag = row
    base_amount = float(base_amount or 0.0)
    if base_amount <= 0: conn.close(); return False, "Nothing to expire"
    expired_base = min(base_qty, base_amount)
    new_amount = base_amount - expired_base
    price_pb = effective_price_per_base(price_per_base, ppu_legacy, unit_row, base_unit)
    lost_value = round(expired_base * float(price_pb or 0.0), 2)
    step_inc = _compute_step_count(qty_ui, ui_unit)
    c.execute("""
        UPDATE inventory
        SET base_amount=?, money_lost=COALESCE(money_lost,0)+?, expired_count=COALESCE(expired_count,0)+?,
            last_used_month=strftime('%Y-%m','now')
        WHERE id=?
    """, (new_amount, lost_value, int(step_inc), item_id))
    conn.commit(); conn.close()
    expired_ui = from_base(expired_base, ui_unit)
    _log_usage(user_id, item_id, "expired", expired_ui, (unit_row or ui_unit), step_inc, lost_value)
    if new_amount <= 0 and int(stable_flag or 0) == 0:
        delete_item(item_id)
        return True, f"Expired {expired_ui:.2f} {ui_unit}. Lost ₪{lost_value:.2f} — item removed."
    return True, f"Expired {expired_ui:.2f} {ui_unit}. Lost ₪{lost_value:.2f}"

def expire_all(item_id: int) -> Tuple[bool, str]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT user_id, base_amount, price_per_base, name, unit, price_per_unit, base_unit, COALESCE(stable,0)
      FROM inventory WHERE id=?
    """, (item_id,))
    row = c.fetchone()
    if not row: conn.close(); return False, "Item not found"
    user_id, base_amount, price_per_base, name, unit_row, ppu_legacy, base_unit, stable_flag = row
    base_amount = float(base_amount or 0.0)
    if base_amount <= 0: conn.close(); return False, f"Nothing to expire for {name}"
    price_pb = effective_price_per_base(price_per_base, ppu_legacy, unit_row, base_unit)
    loss = round(base_amount * float(price_pb or 0.0), 2)
    step_inc = _compute_step_count(base_amount, base_unit or "pcs")
    conn.close()
    _log_usage(user_id, item_id, "expired", base_amount, (base_unit or "pcs"), step_inc, loss)
    if int(stable_flag or 0) == 0:
        delete_item(item_id)
        return True, f"Expired all of {name}. Lost ₪{loss:.2f} (removed)"
    else:
        ff = FAR_FUTURE.strftime("%Y-%m-%d")
        conn2 = get_connection()
        conn2.execute("""
            UPDATE inventory
            SET base_amount=0, money_lost=COALESCE(money_lost,0)+?, expired_count=COALESCE(expired_count,0)+?,
                last_used_month=strftime('%Y-%m','now'),
                expiration=?, storage_state='fresh', frozen_at=NULL, thawed_at=NULL
            WHERE id=?
        """, (loss, int(step_inc), ff, item_id))
        conn2.commit(); conn2.close()
        return True, f"Expired all of {name}. Lost ₪{loss:.2f}"

def freeze_item(item_id: int) -> Tuple[bool, str]:
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT storage_state FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row: conn.close(); return False, "Item not found"
    if row[0] == "frozen": conn.close(); return False, "Already frozen"
    c.execute("UPDATE inventory SET storage_state='frozen', frozen_at=? WHERE id=?", (iso_today(), item_id))
    conn.commit(); conn.close()
    return True, "Frozen"

def thaw_item(item_id: int) -> Tuple[bool, str]:
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT storage_state, frozen_at, COALESCE(frozen_days_accum,0) FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row: conn.close(); return False, "Item not found"
    state, frozen_at, accum = row
    if state != "frozen": conn.close(); return False, "Not frozen"
    extra = 0
    if frozen_at:
        try: extra = (today() - parse_iso(frozen_at)).days
        except Exception: extra = 0
    c.execute("""
        UPDATE inventory
        SET storage_state='fresh', thawed_at=?, frozen_days_accum=?, frozen_at=NULL
        WHERE id=?
    """, (iso_today(), int(accum) + max(0, extra), item_id))
    conn.commit(); conn.close()
    return True, "Thawed"

# ---------------------------------
# Cleanup & export
# ---------------------------------
def normalize_stable_zero_expiry(user_id: int) -> int:
    conn = get_connection(); c = conn.cursor()
    ff = FAR_FUTURE.strftime("%Y-%m-%d")
    c.execute("""
        UPDATE inventory SET expiration=?
        WHERE user_id=? AND COALESCE(stable,0)=1 AND COALESCE(base_amount,0)<=0 AND date(expiration) < date(?)
    """, (ff, user_id, ff))
    updated = c.rowcount or 0
    conn.commit(); conn.close()
    return updated

def cleanup_depleted_items(user_id: int) -> int:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
        DELETE FROM inventory WHERE user_id=? AND COALESCE(stable,0)=0 AND COALESCE(base_amount,0)<=0
    """, (user_id,))
    deleted = c.rowcount or 0
    conn.commit(); conn.close()
    return deleted

def cleanup_expired_items(user_id: int) -> int:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
        SELECT id, user_id, base_amount, price_per_base, unit, price_per_unit, base_unit, name,
               expiration, storage_state, frozen_at, thawed_at, COALESCE(frozen_days_accum,0),
               COALESCE(stable,0)
        FROM inventory
        WHERE user_id=?
    """, (user_id,))
    rows = c.fetchall()
    removed = 0
    ts, month_key = _today_keys()
    for (item_id, uid, base_amt, ppb, unit_row, ppu_legacy, base_unit, nm,
         expiration, storage_state, frozen_at, thawed_at, frozen_days_accum, stable_flag) in rows:
        base_amt = float(base_amt or 0.0)
        if base_amt <= 0: continue
        eff_exp = effective_expiration(expiration, storage_state, frozen_at, thawed_at, int(frozen_days_accum or 0))
        if eff_exp > today(): continue
        price_pb = effective_price_per_base(ppb, ppu_legacy, unit_row, base_unit)
        loss = round(base_amt * float(price_pb or 0.0), 2)
        step_inc = _compute_step_count(base_amt, base_unit or "pcs")
        c.execute("""
          INSERT INTO usage_log (user_id, item_id, event_type, quantity, unit, step_count, value_shekel, ts, month_key)
          VALUES (?, ?, 'expired', ?, ?, ?, ?, ?, ?)
        """, (uid, item_id, base_amt, (base_unit or "pcs"), int(step_inc), float(loss), ts, month_key))
        if int(stable_flag or 0) == 0:
            c.execute("DELETE FROM inventory WHERE id=?", (item_id,))
            removed += 1
        else:
            ff = FAR_FUTURE.strftime("%Y-%m-%d")
            c.execute("""
                UPDATE inventory
                SET base_amount=0, money_lost=COALESCE(money_lost,0)+?,
                    expired_count=COALESCE(expired_count,0)+?, expiration=?, storage_state='fresh',
                    frozen_at=NULL, thawed_at=NULL
                WHERE id=?
            """, (loss, int(step_inc), ff, item_id))
    conn.commit(); conn.close()
    return removed

def export_csv(rows: List[tuple]) -> bytes:
    out = io.StringIO(); writer = csv.writer(out)
    writer.writerow([
        "id","name","expiration","type","amount_ui","unit_ui","used_count","last_used_month","stable",
        "price_per_unit_legacy","expired_count","money_lost","kind","base_unit","base_amount",
        "total_cost","price_per_base","storage_state","frozen_at","thawed_at","frozen_days_accum",
        "thaw_shelf_life_days","recipe_note"
    ])
    for r in rows: writer.writerow(list(r))
    return out.getvalue().encode("utf-8")

# ---------------------------------
# Effective expiration display helper
# ---------------------------------
def effective_expiration_display(expiration: str,
                                 storage_state: str,
                                 frozen_at: Optional[str],
                                 thawed_at: Optional[str],
                                 frozen_days_accum: int,
                                 stable: bool,
                                 base_amount: float):
    if is_stable_zero(stable, base_amount):
        return FAR_FUTURE, "Not stocked", "#8E8E8E", True
    eff = effective_expiration(expiration, storage_state, frozen_at, thawed_at, frozen_days_accum)
    txt, color = status_badge(eff, storage_state)
    return eff, txt, color, False

# ---------------------------------
# Recipe & batches (domain)
# ---------------------------------
def ensure_recipe(prepared_item_id: int) -> int:
    conn = get_connection(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO recipes(prepared_item_id) VALUES (?)", (prepared_item_id,))
    conn.commit()
    c.execute("SELECT id FROM recipes WHERE prepared_item_id=?", (prepared_item_id,))
    rid = c.fetchone()[0]
    conn.close(); return rid

def recipe_components(user_id: int, prepared_item_id: int) -> List[tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT rc.id, i.name, i.base_unit, rc.quantity_base, i.price_per_base
      FROM recipe_components rc
      JOIN inventory i ON i.id = rc.ingredient_item_id
      JOIN recipes r ON r.id = rc.recipe_id
      WHERE r.prepared_item_id=? AND i.user_id=?
      ORDER BY i.name
    """, (prepared_item_id, user_id))
    rows = c.fetchall(); conn.close()
    return rows

def add_or_update_recipe_component(prepared_item_id: int, ingredient_item_id: int, quantity_base: float):
    rid = ensure_recipe(prepared_item_id)
    conn = get_connection()
    conn.execute("""
      INSERT INTO recipe_components(recipe_id, ingredient_item_id, quantity_base)
      VALUES (?,?,?)
      ON CONFLICT(recipe_id, ingredient_item_id) DO UPDATE SET quantity_base=excluded.quantity_base
    """, (rid, ingredient_item_id, float(quantity_base)))
    conn.commit(); conn.close()

def delete_recipe_component(component_id: int):
    conn = get_connection(); conn.execute("DELETE FROM recipe_components WHERE id=?", (component_id,)); conn.commit(); conn.close()

def push_recipe_cost_to_item(prepared_item_id: int, total_cost: float, expected_yield_base: float):
    price_per_base = (total_cost / expected_yield_base) if expected_yield_base > 0 else 0.0
    conn = get_connection(); conn.execute("UPDATE inventory SET total_cost=?, price_per_base=? WHERE id=?", (total_cost, price_per_base, prepared_item_id))
    conn.commit(); conn.close()

def create_batch(prepared_item_id: int, cooked_at: date, total_yield_base: float, portion_size_base: float,
                 expiration: date, batch_cost: float = 0.0):
    conn = get_connection()
    conn.execute("""
      INSERT INTO batches(prepared_item_id, cooked_at, total_yield_base, portion_size_base, remaining_base, expiration, storage_state, batch_cost)
      VALUES (?,?,?,?,?,?, 'fresh', ?)
    """, (prepared_item_id, cooked_at.strftime("%Y-%m-%d"), float(total_yield_base), float(portion_size_base), float(total_yield_base),
          expiration.strftime("%Y-%m-%d"), float(batch_cost)))
    conn.commit(); conn.close()

def list_batches(prepared_item_id: int) -> List[tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, cooked_at, total_yield_base, portion_size_base, remaining_base, expiration, storage_state
      FROM batches
      WHERE prepared_item_id=?
      ORDER BY date(cooked_at) DESC
    """, (prepared_item_id,))
    rows = c.fetchall(); conn.close()
    return rows

def use_batch_portion(batch_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT remaining_base, portion_size_base FROM batches WHERE id=?", (batch_id,))
    r = c.fetchone()
    if not r: conn.close(); return
    remaining, portion = r
    new_remaining = max(0.0, float(remaining) - float(portion or 0.0))
    c.execute("UPDATE batches SET remaining_base=? WHERE id=?", (new_remaining, batch_id))
    conn.commit(); conn.close()
