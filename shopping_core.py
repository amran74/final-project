# shopping_core.py
# Core logic for shopping: DB migrations, units, stores, price book, suggestions,
# creating/renaming staples, learned shelf-life, and checkout.
#
# No UI code here. Pair with Streamlit UI (Shopping.py).

from __future__ import annotations

import math
from datetime import date, timedelta, datetime
from typing import Dict, List, Optional, Tuple

from db import get_connection, create_tables

# ------------------------------
# Units
# ------------------------------
UNITS = ["pcs", "g", "kg", "mg", "ml", "l"]

BASE_FOR = {"pcs": "pcs", "g": "g", "kg": "g", "mg": "g", "ml": "ml", "l": "ml"}
MULTIPLIER_TO_BASE = {"pcs": 1.0, "mg": 0.001, "g": 1.0, "kg": 1000.0, "ml": 1.0, "l": 1000.0}

# Expanded types so you can tag dessert/baking/snacks without hacking "Other"
FOOD_TYPES = [
    "Dairy", "Meat", "Seafood", "Fruit", "Vegetable", "Grain",
    "Legume", "Baking", "Snack", "Dessert", "Condiment", "Beverage",
    "Pantry", "Frozen", "Other"
]

FAR_FUTURE = "9999-12-31"

def to_base(amount: float, unit: str) -> Tuple[float, str]:
    u = (unit or "pcs").lower()
    if u not in BASE_FOR:
        return float(amount or 0.0), "pcs"
    return float(amount or 0.0) * MULTIPLIER_TO_BASE[u], BASE_FOR[u]

def from_base(amount_base: float, ui_unit: str) -> float:
    u = (ui_unit or "pcs").lower()
    if u == "kg": return amount_base / 1000.0
    if u == "g":  return amount_base
    if u == "mg": return amount_base * 1000.0
    if u == "l":  return amount_base / 1000.0
    if u == "ml": return amount_base
    return amount_base  # pcs

def step_size_for(base_unit: str) -> float:
    return 100.0 if base_unit in ("g", "ml") else 1.0

def iso_today() -> str:
    return date.today().strftime("%Y-%m-%d")

def month_str(d: date) -> str:
    return d.strftime("%Y-%m")

# ------------------------------
# Shelf-life heuristics & learning
# ------------------------------
# Name-specific shelf life (days) for SEALED/UNOPENED pantry items etc.
# Fresh vs opened handling is out of scope; we pick realistic defaults for newly bought items.
NAME_SHELF_LIFE = {
    # bakery & fresh basics
    "bread": 3, "baguette": 1, "pita": 3,
    # dairy
    "milk": 7, "yogurt": 21, "butter": 120, "cheese slices": 21, "labneh": 21,
    # proteins
    "chicken breast": 3, "ground beef": 2,
    # fish
    "frozen fish fillets": 180,
    # canned & jars
    "tuna (can": 1095, "canned tomatoes": 730, "tomato paste": 365,
    "chickpeas (canned)": 730, "beans (canned)": 730,
    # dry goods
    "rice": 365, "pasta": 365, "oats": 365, "flour": 270, "cereal": 365, "couscous": 365, "bulgur": 365,
    # oils, condiments, sauces
    "olive oil": 730, "sunflower oil": 540, "vinegar": 3650, "soy sauce": 730, "peanut butter": 270, "honey": 3650,
    "black pepper": 730, "paprika": 730, "cumin": 730, "cinnamon": 730, "turmeric": 730, "za'atar": 730,
    "cocoa powder": 540,
    # beverages
    "coffee": 365, "tea (bags)": 730,
    # sweets
    "chocolate bar": 365, "chocolate spread": 365, "marshmallows": 365, "halva": 365, "ice cream": 120,
    # fruit & veg
    "tomato": 5, "tomatoes": 5, "cucumber": 5, "cucumbers": 5,
    "potato": 30, "potatoes": 30, "onion": 30, "onions": 30, "garlic": 60,
    "avocado": 4, "bananas": 5, "apples": 30, "oranges": 30, "grapes": 7, "dates": 180,
    "lettuce": 5, "carrots": 30, "bell peppers": 7, "zucchini": 7,
    "parsley": 4, "coriander": 4,
    # staples we already had
    "sugar": 1000, "salt": 1000,
}

# Type-level fallback for when the name doesn’t match anything above.
TYPE_SHELF_LIFE = {
    "Dairy": 14,
    "Meat": 3,
    # Fresh seafood is short; canned/frozen is handled by name/keyword below
    "Seafood": 2,
    "Fruit": 7,
    "Vegetable": 7,
    "Grain": 365,
    "Legume": 540,
    "Baking": 360,
    "Snack": 300,
    "Dessert": 180,
    "Condiment": 540,
    "Beverage": 360,
    "Pantry": 365,
    "Frozen": 365,
    "Other": 365,
}

def _get_learned_shelf_life_days(user_id: int, item_id: int) -> Optional[float]:
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT avg_days FROM item_shelf_life_stats WHERE user_id=? AND item_id=?", (user_id, item_id))
    row = c.fetchone(); conn.close()
    return float(row[0]) if row else None

def _learn_shelf_life_days(user_id: int, item_id: int, days: float):
    if days <= 0: return
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      INSERT INTO item_shelf_life_stats(user_id, item_id, avg_days, samples)
      VALUES (?,?,?,?)
      ON CONFLICT(user_id, item_id) DO UPDATE SET
        avg_days = ((item_shelf_life_stats.avg_days * item_shelf_life_stats.samples) + excluded.avg_days)
                 / (item_shelf_life_stats.samples + 1),
        samples  = item_shelf_life_stats.samples + 1
    """, (user_id, item_id, float(days), 1))
    conn.commit(); conn.close()

def _default_shelf_life_days(name: str, typ: str) -> int:
    nm = (name or "").strip().lower()

    # 1) Exact-ish name overrides
    for key, days in NAME_SHELF_LIFE.items():
        if key in nm:
            return days

    # 2) Keyword-based safety net so weird names still get sane values
    if "frozen" in nm:
        # Generic frozen items keep ~9–12 months. Fish is shorter but covered above.
        return 270
    if "canned" in nm or "(can" in nm or " can)" in nm:
        return 730
    if "paste" in nm and "tomato" in nm:
        return 365

    # 3) Type fallback
    return TYPE_SHELF_LIFE.get(typ, 365)

def suggest_expiration_for(user_id: int, item_id: int, name: str, typ: str) -> str:
    learned = _get_learned_shelf_life_days(user_id, item_id)
    days = int(round(learned)) if learned and learned > 0 else _default_shelf_life_days(name, typ)
    return (date.today() + timedelta(days=days)).strftime("%Y-%m-%d")

# ------------------------------
# Migrations
# ------------------------------
SHOP_MIGRATIONS = [
    ("""
     CREATE TABLE IF NOT EXISTS stores (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       user_id INTEGER NOT NULL,
       name TEXT NOT NULL,
       kind TEXT DEFAULT 'local',
       city TEXT,
       link_url TEXT,
       notes TEXT,
       UNIQUE(user_id, name)
     )
    """,),
    ("""
     CREATE TABLE IF NOT EXISTS store_categories (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       user_id INTEGER NOT NULL,
       store_id INTEGER NOT NULL,
       type TEXT NOT NULL,
       UNIQUE(user_id, store_id, type)
     )
    """,),
    ("""
     CREATE TABLE IF NOT EXISTS store_prices (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       user_id INTEGER NOT NULL,
       store_id INTEGER NOT NULL,
       item_id INTEGER NOT NULL,
       pack_qty REAL NOT NULL,
       pack_unit TEXT NOT NULL,
       pack_price REAL NOT NULL,
       price_per_base REAL NOT NULL,
       last_seen TEXT NOT NULL,
       product_url TEXT
     )
    """,),
    ("""
     CREATE TABLE IF NOT EXISTS shopping_lists (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       user_id INTEGER NOT NULL,
       title TEXT NOT NULL,
       status TEXT DEFAULT 'draft',
       budget REAL,
       created_at TEXT NOT NULL,
       notes TEXT
     )
    """,),
    ("""
     CREATE TABLE IF NOT EXISTS shopping_list_items (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       list_id INTEGER NOT NULL,
       item_id INTEGER NOT NULL,
       desired_qty_base REAL NOT NULL,
       chosen_store_id INTEGER,
       est_unit_price_base REAL,
       est_total REAL,
       expiration TEXT
     )
    """,),
    ("""
     CREATE TABLE IF NOT EXISTS purchases_log (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       user_id INTEGER NOT NULL,
       item_id INTEGER NOT NULL,
       store_id INTEGER,
       qty_base REAL NOT NULL,
       unit_price_base REAL NOT NULL,
       total_paid REAL NOT NULL,
       ts TEXT NOT NULL
     )
    """,),
    ('ALTER TABLE "inventory" ADD COLUMN "always_buy" INTEGER DEFAULT 0',),
    ('ALTER TABLE "inventory" ADD COLUMN "par_level_base" REAL DEFAULT 0.0',),
    ("""
     CREATE TABLE IF NOT EXISTS item_shelf_life_stats (
       user_id INTEGER NOT NULL,
       item_id INTEGER NOT NULL,
       avg_days REAL NOT NULL,
       samples INTEGER NOT NULL,
       PRIMARY KEY (user_id, item_id)
     )
    """,),
]

def run_shopping_migrations():
    """Create/update shopping-related tables and additive inventory columns."""
    create_tables()
    conn = get_connection(); c = conn.cursor()

    # apply base tables & additive inv cols idempotently
    c.execute("PRAGMA table_info(inventory)")
    inv_cols = {row[1] for row in c.fetchall()}
    for (stmt,) in SHOP_MIGRATIONS:
        if stmt.startswith('ALTER TABLE "inventory"') or stmt.startswith("ALTER TABLE inventory"):
            try:
                col = stmt.split('"')[3]
            except Exception:
                col = None
            if col and col in inv_cols:
                continue
        try:
            c.execute(stmt); conn.commit()
        except Exception:
            pass

    # Ensure far-future expiration on empty stable items
    try:
        c.execute("""
          UPDATE inventory
             SET expiration=?
           WHERE COALESCE(stable,0)=1 AND COALESCE(base_amount,0)<=0
        """, (FAR_FUTURE,))
        conn.commit()
    except Exception:
        pass

    conn.close()

# ------------------------------
# Legacy staple name repair -> clean names
# ------------------------------
LEGACY_TO_CLEAN = {
    "Milk 3% 1L": "Milk 3%",
    "Eggs 12-pack": "Eggs",
    "Bread white 750g": "Bread white",
    "Rice 1kg": "Rice",
    "Pasta 500g": "Pasta",
    "Chicken breast 1kg": "Chicken breast",
    "Tomatoes 1kg": "Tomatoes",
    "Cucumbers 1kg": "Cucumbers",
    "Potatoes 1kg": "Potatoes",
    "Onions 1kg": "Onions",
    "Olive oil 750ml": "Olive oil",
    "Sugar 1kg": "Sugar",
    "Salt 1kg": "Salt",
    "Coffee 200g": "Coffee",
}

def migrate_legacy_staple_names(user_id: int):
    """Rename seeded legacy names to clean names. Merge quantities if needed."""
    conn = get_connection(); c = conn.cursor()
    try:
        for old, new in LEGACY_TO_CLEAN.items():
            c.execute("SELECT id, base_amount, total_cost, price_per_base FROM inventory WHERE user_id=? AND name=?",
                      (user_id, old))
            old_row = c.fetchone()
            if not old_row:
                continue
            old_id, old_amt, old_cost, old_ppb = old_row

            c.execute("SELECT id, base_amount, total_cost, price_per_base FROM inventory WHERE user_id=? AND name=?",
                      (user_id, new))
            new_row = c.fetchone()

            if not new_row:
                c.execute("UPDATE inventory SET name=? WHERE id=?", (new, old_id))
                continue

            new_id, new_amt, new_cost, new_ppb = new_row
            total_amt = float(old_amt or 0.0) + float(new_amt or 0.0)
            total_cost = float(old_cost or 0.0) + float(new_cost or 0.0)
            merged_ppb = (total_cost / total_amt) if total_amt > 0 else (new_ppb or old_ppb or 0.0)

            c.execute("""
              UPDATE inventory
                 SET base_amount=?, total_cost=?, price_per_base=?
               WHERE id=?
            """, (total_amt, total_cost, merged_ppb, new_id))

            for tbl in ("store_prices", "purchases_log", "usage_log"):
                c.execute(f"UPDATE {tbl} SET item_id=? WHERE user_id=? AND item_id=?", (new_id, user_id, old_id))
            c.execute("DELETE FROM inventory WHERE id=?", (old_id,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ------------------------------
# Data access helpers
# ------------------------------
def get_inventory(user_id: int) -> List[Tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, name, type, kind, base_unit, base_amount, price_per_base,
             always_buy, COALESCE(par_level_base,0), COALESCE(stable,0)
        FROM inventory
       WHERE user_id=?
       ORDER BY name
    """, (user_id,))
    rows = c.fetchall(); conn.close()
    return rows

def get_item_meta(user_id: int, item_id: int) -> Optional[Tuple[int,str,str,str,float]]:
    """Return (id, name, type, base_unit, price_per_base) or None."""
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, name, type, base_unit, price_per_base
        FROM inventory
       WHERE user_id=? AND id=?
    """, (user_id, item_id))
    row = c.fetchone(); conn.close()
    return row

def get_stores(user_id: int) -> List[Tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, name, kind, city, link_url, COALESCE(notes,'')
        FROM stores
       WHERE user_id=?
       ORDER BY kind, name
    """, (user_id,))
    rows = c.fetchall(); conn.close()
    return rows

def add_or_update_store(user_id: int, name: str, kind: str, city: str, link_url: str, notes: str):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      INSERT INTO stores(user_id, name, kind, city, link_url, notes)
           VALUES (?,?,?,?,?,?)
      ON CONFLICT(user_id, name) DO UPDATE SET
        kind=excluded.kind,
        city=excluded.city,
        link_url=excluded.link_url,
        notes=excluded.notes
    """, (user_id, name.strip(), kind, (city or "").strip() or None,
          (link_url or "").strip() or None, (notes or "").strip() or None))
    conn.commit(); conn.close()

def delete_store(store_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("DELETE FROM store_categories WHERE store_id=?", (store_id,))
    c.execute("DELETE FROM store_prices WHERE store_id=?", (store_id,))
    c.execute("DELETE FROM stores WHERE id=?", (store_id,))
    conn.commit(); conn.close()

def get_store_categories(user_id: int, store_id: int) -> List[str]:
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT type FROM store_categories WHERE user_id=? AND store_id=? ORDER BY type",
              (user_id, store_id))
    rows = [r[0] for r in c.fetchall()]
    conn.close(); return rows

def set_store_categories(user_id: int, store_id: int, types: List[str]):
    conn = get_connection(); c = conn.cursor()
    c.execute("DELETE FROM store_categories WHERE user_id=? AND store_id=?", (user_id, store_id))
    for t in types:
        c.execute("INSERT INTO store_categories(user_id, store_id, type) VALUES (?,?,?)",
                  (user_id, store_id, t))
    conn.commit(); conn.close()

def stores_selling_type(user_id: int, typ: str) -> List[Tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT s.id, s.name, s.kind, s.city, s.link_url, COALESCE(s.notes,'')
        FROM stores s
        JOIN store_categories sc
          ON sc.store_id = s.id AND sc.user_id = s.user_id
       WHERE s.user_id=? AND sc.type=?
       ORDER BY s.name
    """, (user_id, typ))
    rows = c.fetchall(); conn.close()
    return rows

def upsert_store_price(user_id: int, store_id: int, item_id: int,
                       pack_qty: float, pack_unit: str, pack_price: float,
                       product_url: Optional[str] = None):
    base_qty, _ = to_base(pack_qty, pack_unit)
    price_per_base = (pack_price / base_qty) if base_qty > 0 else 0.0
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      INSERT INTO store_prices(user_id, store_id, item_id, pack_qty, pack_unit, pack_price, price_per_base, last_seen, product_url)
      VALUES (?,?,?,?,?,?,?,?,?)
      ON CONFLICT(user_id, store_id, item_id) DO UPDATE SET
        pack_qty=excluded.pack_qty,
        pack_unit=excluded.pack_unit,
        pack_price=excluded.pack_price,
        price_per_base=excluded.price_per_base,
        last_seen=excluded.last_seen,
        product_url=COALESCE(excluded.product_url, product_url)
    """, (user_id, store_id, item_id, float(pack_qty), pack_unit, float(pack_price),
          float(price_per_base), iso_today(), (product_url or None)))
    conn.commit(); conn.close()

def get_store_prices_for_store(user_id: int, store_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT sp.item_id, i.name, i.type, i.base_unit,
             sp.pack_qty, sp.pack_unit, sp.pack_price, sp.price_per_base,
             sp.last_seen, sp.product_url
        FROM store_prices sp
        JOIN inventory i ON i.id = sp.item_id
       WHERE sp.user_id=? AND sp.store_id=?
       ORDER BY i.name
    """, (user_id, store_id))
    rows = c.fetchall(); conn.close()
    return rows

def get_prices_for_item(user_id: int, item_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT s.id, s.name, s.kind, s.link_url,
             sp.pack_qty, sp.pack_unit, sp.pack_price, sp.price_per_base,
             sp.product_url, sp.last_seen
        FROM store_prices sp
        JOIN stores s ON s.id = sp.store_id
       WHERE sp.user_id=? AND sp.item_id=?
       ORDER BY sp.price_per_base ASC
    """, (user_id, item_id))
    rows = c.fetchall(); conn.close()
    return rows

def best_price_for_item(user_id: int, item_id: int) -> Optional[Tuple[int, str, float]]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT sp.store_id, s.name, sp.price_per_base
        FROM store_prices sp
        JOIN stores s ON s.id = sp.store_id
       WHERE sp.user_id=? AND sp.item_id=?
       ORDER BY sp.price_per_base ASC
       LIMIT 1
    """, (user_id, item_id))
    row = c.fetchone(); conn.close()
    return row

def ppb_for_item_at_store(user_id: int, item_id: int, store_id: int) -> float:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT price_per_base FROM store_prices
       WHERE user_id=? AND item_id=? AND store_id=?
    """, (user_id, item_id, store_id))
    row = c.fetchone(); conn.close()
    return float(row[0]) if row and row[0] is not None else 0.0

def set_item_rules(item_id: int, always_buy: bool, par_level_base: float):
    conn = get_connection()
    conn.execute("UPDATE inventory SET always_buy=?, par_level_base=? WHERE id=?",
                 (1 if always_buy else 0, float(par_level_base or 0.0), item_id))
    conn.commit(); conn.close()

# ------------------------------
# Suggestion helpers
# ------------------------------
def recent_daily_usage_base(user_id: int, item_id: int, base_unit: str, horizon_days: int = 60) -> float:
    since = (date.today() - timedelta(days=horizon_days)).strftime("%Y-%m-%d")
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT COALESCE(SUM(step_count),0)
        FROM usage_log
       WHERE user_id=? AND item_id=? AND event_type='used' AND substr(ts,1,10)>=?
    """, (user_id, item_id, since))
    steps = float(c.fetchone()[0] or 0.0)
    conn.close()
    return steps * step_size_for(base_unit) / max(horizon_days, 1)

def suggest_shopping_lines(user_id: int, target_days: int = 14, coverage_threshold_days: int = 7) -> List[Dict]:
    """Return suggested purchase lines with best known unit price and an expiration guess."""
    inv = get_inventory(user_id)
    lines: List[Dict] = []
    for (item_id, name, typ, _kind, base_unit, on_hand, ppb, always_buy, par_base, _stable) in inv:
        on_hand = float(on_hand or 0.0)
        par_base = float(par_base or 0.0)
        avg_daily = recent_daily_usage_base(user_id, item_id, base_unit)
        coverage_days = (on_hand / avg_daily) if avg_daily > 0 else 9e9

        include, desired = False, 0.0
        if always_buy:
            include = True
            desired = max(par_base - on_hand, 0.0) if par_base > 0 else step_size_for(base_unit)
        elif coverage_days < coverage_threshold_days:
            include = True
            target_qty = max(target_days * avg_daily - on_hand, 0.0)
            step = step_size_for(base_unit)
            desired = math.ceil(target_qty / step) * step

        if include and desired > 0.0:
            bp = best_price_for_item(user_id, item_id)
            store_id, store_name, ppb_best = bp if bp else (None, None, float(ppb or 0.0))
            exp = suggest_expiration_for(user_id, item_id, name, typ)
            lines.append({
                "item_id": item_id, "name": name, "type": typ, "base_unit": base_unit,
                "qty_base": round(desired, 2),
                "store_id": store_id, "store_name": store_name,
                "unit_price_base": float(ppb_best or 0.0),
                "est_total": round(float(ppb_best or 0.0) * desired, 2),
                "expiration": exp
            })
    return lines

# ------------------------------
# Budget / spend
# ------------------------------
def month_spend(user_id: int, month_iso: Optional[str] = None) -> float:
    month_iso = month_iso or month_str(date.today())
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT COALESCE(SUM(total_paid),0) FROM purchases_log
       WHERE user_id=? AND substr(ts,1,7)=?
    """, (user_id, month_iso))
    s = float(c.fetchone()[0] or 0.0)
    conn.close()
    return s

# ------------------------------
# Inventory + purchasing
# ------------------------------
def ensure_inventory_item(user_id: int, name: str, typ: str, base_unit: str) -> int:
    """Create if missing; return item_id."""
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT id FROM inventory WHERE user_id=? AND name=?", (user_id, name.strip()))
    row = c.fetchone()
    if row:
        conn.close(); return int(row[0])
    c.execute("""
      INSERT INTO inventory
      (user_id, name, expiration, type, amount, unit, used_count, expired_count, last_used_month, stable,
       price_per_unit, money_lost, frozen_until, perishability,
       kind, base_unit, base_amount, total_cost, price_per_base,
       storage_state, frozen_at, thawed_at, frozen_days_accum, thaw_shelf_life_days, recipe_note,
       always_buy, par_level_base)
      VALUES (?, ?, ?, ?, 0, ?, 0, 0, '', 1,
              0.0, 0.0, NULL, 2,
              'ingredient', ?, 0.0, 0.0, 0.0,
              'fresh', NULL, NULL, 0, NULL, NULL,
              0, 0.0)
    """, (user_id, name.strip(), FAR_FUTURE, typ, base_unit, base_unit))
    item_id = c.lastrowid
    conn.commit(); conn.close()
    return int(item_id)

def _purchase_into_inventory(user_id: int, item_id: int, qty_base: float,
                             unit_price_base: float, total_paid: float,
                             store_id: Optional[int], expiration: Optional[str], ts_iso: str):
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT base_amount, total_cost, price_per_base FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close(); return
    base_amount, total_cost, old_ppb = row
    base_amount = float(base_amount or 0.0)
    total_cost = float(total_cost or 0.0)

    new_base_amount = base_amount + qty_base
    new_total_cost = total_cost + total_paid
    new_ppb = (new_total_cost / new_base_amount) if new_base_amount > 0 else (old_ppb or unit_price_base)

    if expiration:
        c.execute("""
          UPDATE inventory
             SET base_amount=?, total_cost=?, price_per_base=?, expiration=?
           WHERE id=?
        """, (new_base_amount, new_total_cost, new_ppb, expiration, item_id))
    else:
        c.execute("""
          UPDATE inventory
             SET base_amount=?, total_cost=?, price_per_base=?
           WHERE id=?
        """, (new_base_amount, new_total_cost, new_ppb, item_id))

    c.execute("""
      INSERT INTO purchases_log(user_id, item_id, store_id, qty_base, unit_price_base, total_paid, ts)
      VALUES (?,?,?,?,?,?,?)
    """, (user_id, item_id, store_id, qty_base, unit_price_base, total_paid, ts_iso))

    if store_id is not None and unit_price_base > 0:
        c.execute("""
          UPDATE store_prices
             SET last_seen=?
           WHERE user_id=? AND store_id=? AND item_id=?
        """, (ts_iso, user_id, store_id, item_id))

    conn.commit(); conn.close()

# Plain class to avoid dataclass import-time issues under custom loaders
class CartLine:
    __slots__ = ("item_id", "qty_base", "unit_price_base", "store_id", "expiration")

    def __init__(
        self,
        item_id: int,
        qty_base: float,
        unit_price_base: float = 0.0,
        store_id: int | None = None,
        expiration: str | None = None,
    ):
        self.item_id = int(item_id)
        self.qty_base = float(qty_base)
        self.unit_price_base = float(unit_price_base or 0.0)
        self.store_id = store_id
        self.expiration = expiration

def checkout_cart(user_id: int, cart: List[CartLine]) -> Tuple[bool, str]:
    """Apply cart to inventory and purchases_log. Clears nothing; UI owns the cart list."""
    if not cart:
        return False, "Cart is empty."

    ts = iso_today()
    for row in cart:
        meta = get_item_meta(user_id, row.item_id)
        if not meta:
            return False, f"Item {row.item_id} not found."
        _, name, typ, _base_unit, _ppb = meta

        exp = row.expiration or suggest_expiration_for(user_id, row.item_id, name, typ)
        total_paid = float(row.unit_price_base or 0.0) * float(row.qty_base or 0.0)

        _purchase_into_inventory(
            user_id=user_id, item_id=row.item_id, qty_base=float(row.qty_base or 0.0),
            unit_price_base=float(row.unit_price_base or 0.0), total_paid=total_paid,
            store_id=row.store_id, expiration=exp, ts_iso=ts
        )

        # learn from this expiration
        try:
            days = (datetime.fromisoformat(exp).date() - date.today()).days
            _learn_shelf_life_days(user_id, row.item_id, float(days))
        except Exception:
            pass

    return True, "Checkout complete."

# ------------------------------
# Israeli defaults (stores + staples)
# ------------------------------
DEFAULT_ISRAELI_STORES = [
    ("Rami Levy",   "chain", "Nationwide", "https://www.rami-levy.co.il", "", ["Dairy","Fruit","Meat","Grain","Vegetable","Other"]),
    ("Shufersal",   "chain", "Nationwide", "https://www.shufersal.co.il", "", ["Dairy","Fruit","Meat","Grain","Vegetable","Other"]),
    ("Victory",     "chain", "Nationwide", "https://www.victoryonline.co.il", "", ["Dairy","Fruit","Meat","Grain","Vegetable","Other"]),
    ("Yochananof",  "chain", "Nationwide", "https://yochananof.co.il", "", ["Dairy","Fruit","Meat","Grain","Vegetable","Other"]),
    ("Osher Ad",    "chain", "Nationwide", "https://osherad.co.il", "", ["Dairy","Fruit","Meat","Grain","Vegetable","Other"]),
    ("Tiv Taam",    "chain", "Nationwide", "https://www.tivtaam.co.il", "", ["Dairy","Fruit","Meat","Grain","Vegetable","Other"]),
]

# name, type, base_unit, pack_qty, pack_unit, {store: pack_price}
DEFAULT_STAPLES = [
    # Breakfast / Dairy
    ("Milk 3%", "Dairy", "ml", 1000, "ml", {"Rami Levy":5.5, "Shufersal":6.2, "Victory":5.9, "Yochananof":5.7, "Osher Ad":5.4, "Tiv Taam":6.5}),
    ("Yogurt (tub)", "Dairy", "ml", 500, "ml", {"Rami Levy":4.9, "Shufersal":5.9, "Victory":5.5, "Yochananof":5.2, "Osher Ad":4.7, "Tiv Taam":6.2}),
    ("Butter", "Dairy", "g", 200, "g", {"Rami Levy":7.9, "Shufersal":9.5, "Victory":8.9, "Yochananof":8.5, "Osher Ad":7.5, "Tiv Taam":10.5}),
    ("Cheese slices", "Dairy", "g", 200, "g", {"Rami Levy":12.9,"Shufersal":15.9,"Victory":13.9,"Yochananof":13.5,"Osher Ad":12.5,"Tiv Taam":16.9}),
    ("Labneh", "Dairy", "g", 250, "g", {"Rami Levy":8.9, "Shufersal":10.5,"Victory":9.8, "Yochananof":9.4, "Osher Ad":8.5, "Tiv Taam":11.9}),
    ("Eggs", "Dairy", "pcs", 12, "pcs", {"Rami Levy":12.9,"Shufersal":16.9,"Victory":14.9,"Yochananof":13.9,"Osher Ad":12.5,"Tiv Taam":18.9}),
    ("Cereal", "Pantry", "g", 500, "g", {"Rami Levy":13.9,"Shufersal":16.9,"Victory":14.9,"Yochananof":14.5,"Osher Ad":12.9,"Tiv Taam":17.9}),
    ("Oats", "Pantry", "g", 1000, "g", {"Rami Levy":8.9, "Shufersal":10.9,"Victory":9.8, "Yochananof":9.5, "Osher Ad":8.2, "Tiv Taam":11.9}),
    ("Honey", "Condiment", "g", 500, "g", {"Rami Levy":18.9,"Shufersal":22.9,"Victory":20.9,"Yochananof":19.9,"Osher Ad":17.9,"Tiv Taam":24.9}),
    ("Peanut butter", "Condiment", "g", 400, "g", {"Rami Levy":12.5,"Shufersal":14.9,"Victory":13.5,"Yochananof":13.0,"Osher Ad":11.9,"Tiv Taam":15.9}),

    # Proteins / Mains
    ("Chicken breast", "Meat", "g", 1000, "g", {"Rami Levy":29.9,"Shufersal":36.9,"Victory":32.9,"Yochananof":31.9,"Osher Ad":28.9,"Tiv Taam":39.9}),
    ("Ground beef", "Meat", "g", 1000, "g", {"Rami Levy":42.9,"Shufersal":49.9,"Victory":45.9,"Yochananof":44.9,"Osher Ad":41.9,"Tiv Taam":52.9}),
    ("Frozen fish fillets", "Seafood", "g", 1000, "g", {"Rami Levy":39.9,"Shufersal":49.0,"Victory":44.0,"Yochananof":42.9,"Osher Ad":38.9,"Tiv Taam":54.0}),
    ("Tuna (can)", "Seafood", "g", 160, "g", {"Rami Levy":5.9, "Shufersal":6.9, "Victory":6.2, "Yochananof":6.0, "Osher Ad":5.5, "Tiv Taam":7.5}),
    ("Tofu", "Pantry", "g", 300, "g", {"Rami Levy":7.9, "Shufersal":9.5, "Victory":8.9, "Yochananof":8.5, "Osher Ad":7.4, "Tiv Taam":10.5}),
    ("Chickpeas (dry)", "Legume", "g", 1000, "g", {"Rami Levy":8.9, "Shufersal":10.9,"Victory":9.9, "Yochananof":9.5, "Osher Ad":8.5, "Tiv Taam":11.9}),
    ("Chickpeas (canned)", "Legume", "g", 540, "g", {"Rami Levy":4.9, "Shufersal":5.9, "Victory":5.5, "Yochananof":5.2, "Osher Ad":4.5, "Tiv Taam":6.5}),
    ("Lentils", "Legume", "g", 1000, "g", {"Rami Levy":9.5, "Shufersal":11.9,"Victory":10.5,"Yochananof":10.2,"Osher Ad":8.9, "Tiv Taam":12.9}),
    ("Beans (canned)", "Legume", "g", 540, "g", {"Rami Levy":4.9, "Shufersal":5.9, "Victory":5.5, "Yochananof":5.2, "Osher Ad":4.5, "Tiv Taam":6.5}),

    # Carbs & Grains / Breads
    ("Bread white", "Grain", "g", 750, "g", {"Rami Levy":7.9, "Shufersal":9.9, "Victory":8.5, "Yochananof":8.9, "Osher Ad":7.5, "Tiv Taam":10.5}),
    ("Rice", "Grain", "g", 1000, "g", {"Rami Levy":6.9, "Shufersal":8.5, "Victory":7.5, "Yochananof":7.2, "Osher Ad":6.5, "Tiv Taam":9.0}),
    ("Pasta", "Grain", "g", 500, "g", {"Rami Levy":3.9, "Shufersal":5.5, "Victory":4.5, "Yochananof":4.2, "Osher Ad":3.5, "Tiv Taam":5.9}),
    ("Couscous", "Grain", "g", 500, "g", {"Rami Levy":5.9, "Shufersal":7.5, "Victory":6.5, "Yochananof":6.2, "Osher Ad":5.5, "Tiv Taam":8.0}),
    ("Bulgur", "Grain", "g", 1000, "g", {"Rami Levy":9.9, "Shufersal":12.5,"Victory":10.9,"Yochananof":10.5,"Osher Ad":9.2, "Tiv Taam":13.5}),
    ("Tortilla wraps", "Grain", "pcs", 8, "pcs", {"Rami Levy":9.9, "Shufersal":12.9,"Victory":11.5,"Yochananof":11.0,"Osher Ad":9.5, "Tiv Taam":13.9}),
    ("Pita", "Grain", "pcs", 10, "pcs", {"Rami Levy":8.9, "Shufersal":10.9,"Victory":9.8, "Yochananof":9.5, "Osher Ad":8.5, "Tiv Taam":11.9}),
    ("Baguette", "Grain", "pcs", 1, "pcs", {"Rami Levy":4.0, "Shufersal":5.0, "Victory":4.5, "Yochananof":4.5, "Osher Ad":3.9, "Tiv Taam":5.5}),

    # Vegetables / Salad base
    ("Tomatoes", "Vegetable", "g", 1000, "g", {"Rami Levy":3.9, "Shufersal":5.9, "Victory":4.5, "Yochananof":4.2, "Osher Ad":3.5, "Tiv Taam":6.9}),
    ("Cucumbers", "Vegetable", "g", 1000, "g", {"Rami Levy":3.9, "Shufersal":5.5, "Victory":4.2, "Yochananof":4.0, "Osher Ad":3.5, "Tiv Taam":6.5}),
    ("Potatoes", "Vegetable", "g", 1000, "g", {"Rami Levy":2.9, "Shufersal":4.5, "Victory":3.5, "Yochananof":3.2, "Osher Ad":2.7, "Tiv Taam":4.9}),
    ("Onions", "Vegetable", "g", 1000, "g", {"Rami Levy":2.9, "Shufersal":4.5, "Victory":3.5, "Yochananof":3.2, "Osher Ad":2.8, "Tiv Taam":4.9}),
    ("Avocado", "Fruit", "pcs", 1, "pcs", {"Rami Levy":4.5, "Shufersal":6.0, "Victory":5.0, "Yochananof":5.5, "Osher Ad":4.9, "Tiv Taam":6.5}),
    ("Lettuce", "Vegetable", "pcs", 1, "pcs", {"Rami Levy":5.9, "Shufersal":7.5, "Victory":6.9, "Yochananof":6.5, "Osher Ad":5.5, "Tiv Taam":7.9}),
    ("Carrots", "Vegetable", "g", 1000, "g", {"Rami Levy":3.5, "Shufersal":4.9, "Victory":4.0, "Yochananof":3.9, "Osher Ad":3.2, "Tiv Taam":5.5}),
    ("Bell peppers", "Vegetable", "g", 1000, "g", {"Rami Levy":7.9, "Shufersal":9.9, "Victory":8.9, "Yochananof":8.5, "Osher Ad":7.5, "Tiv Taam":10.9}),
    ("Zucchini", "Vegetable", "g", 1000, "g", {"Rami Levy":5.9, "Shufersal":7.9, "Victory":6.9, "Yochananof":6.5, "Osher Ad":5.2, "Tiv Taam":8.9}),
    ("Garlic", "Vegetable", "g", 200, "g", {"Rami Levy":3.9, "Shufersal":5.0, "Victory":4.5, "Yochananof":4.2, "Osher Ad":3.5, "Tiv Taam":5.5}),
    ("Parsley (bunch)", "Vegetable", "pcs", 1, "pcs", {"Rami Levy":2.5, "Shufersal":3.5, "Victory":3.0, "Yochananof":3.0, "Osher Ad":2.5, "Tiv Taam":3.9}),
    ("Coriander (bunch)", "Vegetable", "pcs", 1, "pcs", {"Rami Levy":2.5, "Shufersal":3.5, "Victory":3.0, "Yochananof":3.0, "Osher Ad":2.5, "Tiv Taam":3.9}),

    # Fruits
    ("Apples", "Fruit", "g", 1000, "g", {"Rami Levy":6.9, "Shufersal":8.5, "Victory":7.5, "Yochananof":7.2, "Osher Ad":6.5, "Tiv Taam":9.0}),
    ("Bananas", "Fruit", "g", 1000, "g", {"Rami Levy":5.5, "Shufersal":6.9, "Victory":6.0, "Yochananof":6.0, "Osher Ad":5.2, "Tiv Taam":7.5}),
    ("Oranges", "Fruit", "g", 1000, "g", {"Rami Levy":4.9, "Shufersal":6.2, "Victory":5.5, "Yochananof":5.2, "Osher Ad":4.7, "Tiv Taam":6.9}),
    ("Grapes", "Fruit", "g", 1000, "g", {"Rami Levy":9.9, "Shufersal":12.5,"Victory":11.0,"Yochananof":10.9,"Osher Ad":9.5, "Tiv Taam":13.9}),
    ("Dates", "Dessert", "g", 500, "g", {"Rami Levy":14.9,"Shufersal":18.9,"Victory":16.9,"Yochananof":16.2,"Osher Ad":14.5,"Tiv Taam":19.9}),

    # Desserts / Baking
    ("Chocolate bar", "Dessert", "g", 100, "g", {"Rami Levy":4.5, "Shufersal":5.5, "Victory":5.0, "Yochananof":5.0, "Osher Ad":4.2, "Tiv Taam":6.0}),
    ("Biscuits", "Dessert", "g", 250, "g", {"Rami Levy":6.5, "Shufersal":7.9, "Victory":7.0, "Yochananof":7.0, "Osher Ad":6.2, "Tiv Taam":8.5}),
    ("Ice cream (tub)", "Frozen", "ml", 1000, "ml", {"Rami Levy":19.9,"Shufersal":24.9,"Victory":22.9,"Yochananof":22.5,"Osher Ad":18.9,"Tiv Taam":26.9}),
    ("Halva", "Dessert", "g", 400, "g", {"Rami Levy":12.9,"Shufersal":15.9,"Victory":14.5,"Yochananof":14.0,"Osher Ad":12.5,"Tiv Taam":16.9}),
    ("Chocolate spread", "Dessert", "g", 350, "g", {"Rami Levy":9.9, "Shufersal":12.5,"Victory":11.0,"Yochananof":10.9,"Osher Ad":9.2, "Tiv Taam":13.5}),
    ("Marshmallows", "Dessert", "g", 200, "g", {"Rami Levy":5.5, "Shufersal":6.9, "Victory":6.0, "Yochananof":6.0, "Osher Ad":5.0, "Tiv Taam":7.5}),
    ("Flour", "Baking", "g", 1000, "g", {"Rami Levy":5.0, "Shufersal":6.5, "Victory":5.7, "Yochananof":5.5, "Osher Ad":4.9, "Tiv Taam":6.9}),
    ("Sugar", "Baking", "g", 1000, "g", {"Rami Levy":5.0, "Shufersal":6.5, "Victory":5.7, "Yochananof":5.5, "Osher Ad":4.9, "Tiv Taam":6.9}),
    ("Baking powder", "Baking", "g", 100, "g", {"Rami Levy":3.0, "Shufersal":3.9, "Victory":3.5, "Yochananof":3.5, "Osher Ad":3.0, "Tiv Taam":4.5}),
    ("Vanilla sugar", "Baking", "g", 100, "g", {"Rami Levy":4.0, "Shufersal":4.9, "Victory":4.5, "Yochananof":4.5, "Osher Ad":3.9, "Tiv Taam":5.5}),
    ("Cocoa powder", "Baking", "g", 200, "g", {"Rami Levy":9.9, "Shufersal":12.5,"Victory":11.5,"Yochananof":11.0,"Osher Ad":9.5, "Tiv Taam":13.5}),

    # Oils / Condiments / Spices
    ("Olive oil", "Condiment", "ml", 750, "ml", {"Rami Levy":24.9,"Shufersal":29.9,"Victory":26.9,"Yochananof":25.9,"Osher Ad":23.9,"Tiv Taam":34.9}),
    ("Sunflower oil", "Condiment", "ml", 1000, "ml", {"Rami Levy":9.9, "Shufersal":12.5,"Victory":11.0,"Yochananof":10.9,"Osher Ad":9.5, "Tiv Taam":13.5}),
    ("Vinegar", "Condiment", "ml", 500, "ml", {"Rami Levy":4.5, "Shufersal":5.5, "Victory":5.0, "Yochananof":5.0, "Osher Ad":4.2, "Tiv Taam":6.0}),
    ("Soy sauce", "Condiment", "ml", 500, "ml", {"Rami Levy":9.9, "Shufersal":12.9,"Victory":11.5,"Yochananof":11.0,"Osher Ad":9.5, "Tiv Taam":13.9}),
    ("Tomato paste", "Pantry", "g", 200, "g", {"Rami Levy":3.5, "Shufersal":4.5, "Victory":4.0, "Yochananof":4.0, "Osher Ad":3.2, "Tiv Taam":5.0}),
    ("Canned tomatoes", "Pantry", "g", 400, "g", {"Rami Levy":4.9, "Shufersal":5.9, "Victory":5.5, "Yochananof":5.2, "Osher Ad":4.5, "Tiv Taam":6.5}),
    ("Black pepper (ground)", "Condiment", "g", 100, "g", {"Rami Levy":8.9, "Shufersal":10.9,"Victory":9.8, "Yochananof":9.5, "Osher Ad":8.5, "Tiv Taam":11.9}),
    ("Paprika", "Condiment", "g", 100, "g", {"Rami Levy":5.9, "Shufersal":7.5, "Victory":6.9, "Yochananof":6.5, "Osher Ad":5.5, "Tiv Taam":8.5}),
    ("Cumin", "Condiment", "g", 100, "g", {"Rami Levy":6.9, "Shufersal":8.5, "Victory":7.9, "Yochananof":7.5, "Osher Ad":6.5, "Tiv Taam":9.5}),
    ("Cinnamon", "Condiment", "g", 50, "g", {"Rami Levy":6.9, "Shufersal":8.5, "Victory":7.9, "Yochananof":7.5, "Osher Ad":6.5, "Tiv Taam":9.5}),
    ("Turmeric", "Condiment", "g", 100, "g", {"Rami Levy":5.9, "Shufersal":7.5, "Victory":6.9, "Yochananof":6.5, "Osher Ad":5.5, "Tiv Taam":8.5}),
    ("Za'atar", "Condiment", "g", 100, "g", {"Rami Levy":7.9, "Shufersal":9.9, "Victory":8.9, "Yochananof":8.5, "Osher Ad":7.5, "Tiv Taam":10.9}),

    # Beverages
    ("Coffee", "Beverage", "g", 200, "g", {"Rami Levy":17.9,"Shufersal":22.9,"Victory":19.9,"Yochananof":19.5,"Osher Ad":17.5,"Tiv Taam":24.9}),
    ("Tea (bags)", "Beverage", "pcs", 25, "pcs", {"Rami Levy":6.9, "Shufersal":8.9, "Victory":7.9, "Yochananof":7.9, "Osher Ad":6.5, "Tiv Taam":9.9}),
]

def seed_israel_defaults(user_id: int):
    """Create stores (if absent), map categories, migrate legacy names, and seed price book."""
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM stores WHERE user_id=?", (user_id,))
    has_store = int(c.fetchone()[0] or 0) > 0

    names_to_id: Dict[str, int] = {}

    if not has_store:
        for name, kind, city, link_url, notes, cats in DEFAULT_ISRAELI_STORES:
            add_or_update_store(user_id, name, kind, city, link_url, notes)
        conn.commit()
        c.execute("SELECT id, name FROM stores WHERE user_id=?", (user_id,))
        for sid, sname in c.fetchall():
            names_to_id[sname] = sid
            cats = next((s[-1] for s in DEFAULT_ISRAELI_STORES if s[0] == sname), [])
            for t in cats:
                c.execute("INSERT OR IGNORE INTO store_categories(user_id, store_id, type) VALUES (?,?,?)",
                          (user_id, sid, t))
        conn.commit()
    else:
        c.execute("SELECT id, name FROM stores WHERE user_id=?", (user_id,))
        for sid, sname in c.fetchall():
            names_to_id[sname] = sid

    migrate_legacy_staple_names(user_id)

    for item_name, typ, base_unit, pack_qty, pack_unit, price_map in DEFAULT_STAPLES:
        item_id = ensure_inventory_item(user_id, item_name, typ, base_unit)
        for store_name, pack_price in price_map.items():
            sid = names_to_id.get(store_name)
            if not sid:
                continue
            upsert_store_price(user_id, sid, item_id, pack_qty, pack_unit, float(pack_price), product_url=None)

    conn.close()

# ------------------------------
# Convenience: create new item and save price for a store
# ------------------------------
def create_item_and_price(user_id: int, name: str, typ: str, base_unit: str,
                          store_id: int, pack_qty: float, pack_unit: str, pack_price: float,
                          product_url: Optional[str] = None) -> int:
    """Create a new inventory item (Stable) if needed and save its price for a specific store."""
    item_id = ensure_inventory_item(user_id, name.strip(), typ, BASE_FOR.get(base_unit, "pcs"))
    upsert_store_price(user_id, store_id, item_id, pack_qty, pack_unit, pack_price, product_url=product_url)
    return item_id
