# Shopping.py — Stores (with categories), price book, AI list builder, cart & checkout
# Deeply connected to Inventory:
# - Stores track what categories they sell (Dairy/Meat/Vegetable/etc.)
# - Create new items directly from Shopping: price + Buy -> adds to Inventory as Stable
# - Per-store "Buy pack" buttons update Inventory & purchases_log immediately
# - Stable items can be mapped to stores that sell their category
# - Store pickers only show stores that sell the current item's category

import streamlit as st
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
import math

from db import (
    get_connection,
    create_tables,
    _today_keys,  # timestamp helper used by Inventory
)

# --------------------------------
# Shared unit helpers (mirror Inventory)
# --------------------------------
UNITS = ["pcs", "g", "kg", "mg", "ml", "l"]
BASE_FOR = {"pcs": "pcs", "g": "g", "kg": "g", "mg": "g", "ml": "ml", "l": "ml"}
MULTIPLIER_TO_BASE = {"pcs": 1.0, "mg": 0.001, "g": 1.0, "kg": 1000.0, "ml": 1.0, "l": 1000.0}
FOOD_TYPES = ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"]

def to_base(amount: float, unit: str) -> Tuple[float, str]:
    unit = (unit or "pcs").lower()
    if unit not in BASE_FOR:
        return float(amount or 0.0), "pcs"
    return float(amount or 0.0) * MULTIPLIER_TO_BASE[unit], BASE_FOR[unit]

def from_base(amount_base: float, ui_unit: str) -> float:
    ui_unit = (ui_unit or "pcs").lower()
    if ui_unit == "kg":  return amount_base / 1000.0
    if ui_unit == "g":   return amount_base
    if ui_unit == "mg":  return amount_base * 1000.0
    if ui_unit == "l":   return amount_base / 1000.0
    if ui_unit == "ml":  return amount_base
    return amount_base

def step_size_for(base_unit: str) -> float:
    return 100.0 if base_unit in ("g", "ml") else 1.0

def iso_today() -> str:
    return date.today().strftime("%Y-%m-%d")


# --------------------------------
# Migrations (shopping + inventory helpers)
# --------------------------------
SHOP_MIGRATIONS = [
    # Stores catalog
    ("CREATE TABLE IF NOT EXISTS stores ("
     "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
     "  user_id INTEGER NOT NULL,"
     "  name TEXT NOT NULL,"
     "  kind TEXT DEFAULT 'local',"       -- local | chain | greengrocer | online
     "  city TEXT,"
     "  link_url TEXT,"
     "  notes TEXT,"
     "  UNIQUE(user_id, name)"
     ")",),
    # What each store sells (by food type from inventory)
    ("CREATE TABLE IF NOT EXISTS store_categories ("
     "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
     "  user_id INTEGER NOT NULL,"
     "  store_id INTEGER NOT NULL,"
     "  type TEXT NOT NULL,"
     "  UNIQUE(user_id, store_id, type)"
     ")",),
    # Store item prices (price book)
    ("CREATE TABLE IF NOT EXISTS store_prices ("
     "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
     "  user_id INTEGER NOT NULL,"
     "  store_id INTEGER NOT NULL,"
     "  item_id INTEGER NOT NULL,"            -- inventory.id
     "  pack_qty REAL NOT NULL,"
     "  pack_unit TEXT NOT NULL,"
     "  pack_price REAL NOT NULL,"
     "  price_per_base REAL NOT NULL,"        -- ₪/base
     "  last_seen TEXT NOT NULL,"
     "  UNIQUE(user_id, store_id, item_id)"
     ")",),
    # Shopping lists (templates/sessions)
    ("CREATE TABLE IF NOT EXISTS shopping_lists ("
     "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
     "  user_id INTEGER NOT NULL,"
     "  title TEXT NOT NULL,"
     "  status TEXT DEFAULT 'draft',"          -- draft | purchased | template
     "  budget REAL,"
     "  created_at TEXT NOT NULL,"
     "  notes TEXT"
     ")",),
    ("CREATE TABLE IF NOT EXISTS shopping_list_items ("
     "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
     "  list_id INTEGER NOT NULL,"
     "  item_id INTEGER NOT NULL,"             -- inventory.id
     "  desired_qty_base REAL NOT NULL,"
     "  chosen_store_id INTEGER,"
     "  est_unit_price_base REAL,"
     "  est_total REAL,"
     "  expiration TEXT"
     ")",),
    # Purchases log (separate from usage_log)
    ("CREATE TABLE IF NOT EXISTS purchases_log ("
     "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
     "  user_id INTEGER NOT NULL,"
     "  item_id INTEGER NOT NULL,"
     "  store_id INTEGER,"
     "  qty_base REAL NOT NULL,"
     "  unit_price_base REAL NOT NULL,"
     "  total_paid REAL NOT NULL,"
     "  ts TEXT NOT NULL"
     ")",),
    # Inventory helpers for shopping rules
    ("ALTER TABLE inventory ADD COLUMN always_buy INTEGER DEFAULT 0",),
    ("ALTER TABLE inventory ADD COLUMN par_level_base REAL DEFAULT 0.0",),
]

def run_shopping_migrations():
    conn = get_connection(); c = conn.cursor()
    c.execute("PRAGMA table_info(inventory)")
    inv_cols = {row[1] for row in c.fetchall()}
    for mig in SHOP_MIGRATIONS:
        stmt = mig[0]
        if stmt.startswith("ALTER TABLE inventory"):
            col = stmt.split(" ADD COLUMN ")[1].split(" ")[0]
            if col in inv_cols:
                continue
        try:
            c.execute(stmt); conn.commit()
        except Exception:
            pass
    conn.close()


# --------------------------------
# Data access helpers
# --------------------------------
def get_inventory(user_id: int) -> List[tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, name, type, kind, base_unit, base_amount, price_per_base, always_buy, COALESCE(par_level_base,0), COALESCE(stable,0)
      FROM inventory
      WHERE user_id=?
      ORDER BY name
    """, (user_id,))
    rows = c.fetchall(); conn.close()
    return rows

def get_stores(user_id: int) -> List[tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, name, kind, city, link_url, COALESCE(notes,'')
      FROM stores WHERE user_id=?
      ORDER BY kind, name
    """, (user_id,))
    rows = c.fetchall(); conn.close()
    return rows

def get_store_categories(user_id: int, store_id: int) -> List[str]:
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT type FROM store_categories WHERE user_id=? AND store_id=? ORDER BY type", (user_id, store_id))
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows

def set_store_categories(user_id: int, store_id: int, types: List[str]):
    conn = get_connection(); c = conn.cursor()
    c.execute("DELETE FROM store_categories WHERE user_id=? AND store_id=?", (user_id, store_id))
    for t in types:
        c.execute("INSERT INTO store_categories(user_id, store_id, type) VALUES (?,?,?)", (user_id, store_id, t))
    conn.commit(); conn.close()

def stores_selling_type(user_id: int, typ: str) -> List[tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT s.id, s.name, s.kind, s.city, s.link_url, COALESCE(s.notes,'')
      FROM stores s
      JOIN store_categories sc ON sc.store_id = s.id AND sc.user_id = s.user_id
      WHERE s.user_id=? AND sc.type=?
      ORDER BY s.name
    """, (user_id, typ))
    rows = c.fetchall(); conn.close()
    return rows

def add_or_update_store(user_id: int, name: str, kind: str, city: str, link_url: str, notes: str):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      INSERT INTO stores(user_id, name, kind, city, link_url, notes)
      VALUES (?,?,?,?,?,?)
      ON CONFLICT(user_id, name) DO UPDATE SET
        kind=excluded.kind, city=excluded.city, link_url=excluded.link_url, notes=excluded.notes
    """, (user_id, name.strip(), kind, city.strip() if city else None, link_url.strip() if link_url else None, notes.strip() if notes else None))
    conn.commit(); conn.close()

def delete_store(store_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("DELETE FROM store_categories WHERE store_id=?", (store_id,))
    c.execute("DELETE FROM store_prices WHERE store_id=?", (store_id,))
    c.execute("DELETE FROM stores WHERE id=?", (store_id,))
    conn.commit(); conn.close()

def upsert_store_price(user_id: int, store_id: int, item_id: int,
                       pack_qty: float, pack_unit: str, pack_price: float):
    base_qty, base_unit = to_base(pack_qty, pack_unit)
    price_per_base = (pack_price / base_qty) if base_qty > 0 else 0.0
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      INSERT INTO store_prices(user_id, store_id, item_id, pack_qty, pack_unit, pack_price, price_per_base, last_seen)
      VALUES (?,?,?,?,?,?,?,?)
      ON CONFLICT(user_id, store_id, item_id) DO UPDATE SET
        pack_qty=excluded.pack_qty, pack_unit=excluded.pack_unit, pack_price=excluded.pack_price,
        price_per_base=excluded.price_per_base, last_seen=excluded.last_seen
    """, (user_id, store_id, item_id, float(pack_qty), pack_unit, float(pack_price), float(price_per_base), iso_today()))
    conn.commit(); conn.close()

def get_store_prices_for_store(user_id: int, store_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT sp.item_id, i.name, i.type, i.base_unit, sp.pack_qty, sp.pack_unit, sp.pack_price, sp.price_per_base, sp.last_seen
      FROM store_prices sp
      JOIN inventory i ON i.id = sp.item_id
      WHERE sp.user_id=? AND sp.store_id=?
      ORDER BY i.name
    """, (user_id, store_id))
    rows = c.fetchall(); conn.close()
    return rows

def best_price_for_item(user_id: int, item_id: int) -> Optional[tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT sp.store_id, s.name, sp.price_per_base
      FROM store_prices sp JOIN stores s ON s.id=sp.store_id
      WHERE sp.user_id=? AND sp.item_id=?
      ORDER BY sp.price_per_base ASC
      LIMIT 1
    """, (user_id, item_id))
    row = c.fetchone(); conn.close()
    return row

def set_item_rules(item_id: int, always_buy: bool, par_level_base: float):
    conn = get_connection()
    conn.execute("UPDATE inventory SET always_buy=?, par_level_base=? WHERE id=?",
                 (1 if always_buy else 0, float(par_level_base or 0.0), item_id))
    conn.commit(); conn.close()


# --------------------------------
# Usage rate from usage_log
# --------------------------------
def recent_daily_usage_base(user_id: int, item_id: int, base_unit: str, horizon_days: int = 60) -> float:
    since = (date.today() - timedelta(days=horizon_days)).strftime("%Y-%m-%d")
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT COALESCE(SUM(step_count),0)
      FROM usage_log
      WHERE user_id=? AND item_id=? AND event_type='used' AND substr(ts,1,10)>=?
    """, (user_id, item_id, since))
    steps = float(c.fetchone()[0] or 0.0); conn.close()
    return steps * step_size_for(base_unit) / max(horizon_days, 1)


# --------------------------------
# Smart list builder
# --------------------------------
def suggest_shopping_lines(user_id: int,
                           target_days: int = 14,
                           coverage_threshold_days: int = 7) -> List[Dict]:
    inv = get_inventory(user_id)
    lines = []
    for (item_id, name, typ, kind, base_unit, on_hand, ppb, always_buy, par_base, stable_flag) in inv:
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
            store_id, store_name, ppb_best = (bp if bp else (None, None, float(ppb or 0.0)))
            lines.append({
                "item_id": item_id, "name": name, "type": typ,
                "base_unit": base_unit, "qty_base": round(desired, 2),
                "store_id": store_id, "store_name": store_name,
                "unit_price_base": float(ppb_best or 0.0),
                "est_total": round(float(ppb_best or 0.0) * desired, 2),
                "suggested": True, "expiration": None,
            })
    return lines


# --------------------------------
# Cart management
# --------------------------------
def _ensure_cart():
    if "cart" not in st.session_state:
        st.session_state.cart = []

def add_to_cart(row: Dict):
    _ensure_cart(); st.session_state.cart.append(row)

def remove_from_cart(idx: int):
    _ensure_cart()
    if 0 <= idx < len(st.session_state.cart):
        del st.session_state.cart[idx]

def clear_cart():
    st.session_state.cart = []


# --------------------------------
# Inventory create & purchase helpers (tight coupling)
# --------------------------------
def _insert_inventory_item_stable(user_id: int, name: str, typ: str,
                                  qty_base: float, base_unit: str,
                                  price_per_base: float, total_cost: float,
                                  expiration: Optional[str]) -> int:
    """Create inventory item as Stable with initial quantity (qty_base). Returns new item_id."""
    conn = get_connection(); c = conn.cursor()
    # We'll store UI unit equal to base_unit for clarity
    amount_ui = from_base(qty_base, base_unit)
    c.execute("""
      INSERT INTO inventory
      (user_id, name, expiration, type, amount, unit, used_count, last_used_month, stable,
       price_per_unit, expired_count, money_lost,
       kind, base_unit, base_amount, total_cost, price_per_base,
       storage_state, frozen_at, thawed_at, frozen_days_accum, thaw_shelf_life_days, recipe_note,
       always_buy, par_level_base)
      VALUES (?, ?, ?, ?, ?, ?, 0, strftime('%Y-%m','now'), 1,
              0.0, 0, 0.0,
              'ingredient', ?, ?, ?, ?, 'fresh', NULL, NULL, 0, NULL, NULL,
              1, 0.0)
    """, (user_id, name.strip(), (expiration or iso_today()), typ,
          amount_ui, base_unit, base_unit, qty_base, total_cost, price_per_base))
    item_id = c.lastrowid
    conn.commit(); conn.close()
    return item_id

def _purchase_into_inventory(user_id: int, item_id: int, qty_base: float,
                             unit_price_base: float, total_paid: float,
                             store_id: Optional[int], expiration: Optional[str]):
    """Add qty_base to inventory, update moving average, log purchase."""
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT base_amount, total_cost, price_per_base FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close(); return
    base_amount, total_cost, old_ppb = row
    base_amount = float(base_amount or 0.0)
    total_cost  = float(total_cost or 0.0)

    new_base_amount = base_amount + qty_base
    new_total_cost  = total_cost + total_paid
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
    """, (user_id, item_id, store_id, qty_base, unit_price_base, total_paid, iso_today()))

    if store_id is not None and unit_price_base > 0:
        c.execute("""
          UPDATE store_prices SET last_seen=? WHERE user_id=? AND store_id=? AND item_id=?
        """, (iso_today(), user_id, store_id, item_id))

    conn.commit(); conn.close()


# --------------------------------
# Checkout (kept for cart flow)
# --------------------------------
def checkout_cart(user_id: int):
    _ensure_cart()
    if not st.session_state.cart:
        return False, "Cart is empty"
    conn = get_connection(); c = conn.cursor()
    ts = iso_today()

    for row in st.session_state.cart:
        item_id = row["item_id"]
        qty_base = float(row["qty_base"])
        store_id = row.get("store_id")
        unit_price_base = float(row.get("unit_price_base") or 0.0)
        total_paid = unit_price_base * qty_base
        exp = row.get("expiration")

        # Update inventory
        c.execute("SELECT base_amount, total_cost, price_per_base FROM inventory WHERE id=?", (item_id,))
        cur = c.fetchone()
        if not cur:  # item was removed meanwhile
            continue
        base_amount, total_cost, old_ppb = cur
        base_amount = float(base_amount or 0.0); total_cost = float(total_cost or 0.0)
        new_base_amount = base_amount + qty_base
        new_total_cost = total_cost + total_paid
        new_ppb = (new_total_cost / new_base_amount) if new_base_amount > 0 else (old_ppb or unit_price_base)

        if exp:
            c.execute("""
              UPDATE inventory
              SET base_amount=?, total_cost=?, price_per_base=?, expiration=?
              WHERE id=?
            """, (new_base_amount, new_total_cost, new_ppb, exp, item_id))
        else:
            c.execute("""
              UPDATE inventory
              SET base_amount=?, total_cost=?, price_per_base=?
              WHERE id=?
            """, (new_base_amount, new_total_cost, new_ppb, item_id))

        c.execute("""
          INSERT INTO purchases_log(user_id, item_id, store_id, qty_base, unit_price_base, total_paid, ts)
          VALUES (?,?,?,?,?,?,?)
        """, (user_id, item_id, store_id, unit_price_base * 1.0, total_paid, ts))

        if store_id is not None and unit_price_base > 0:
            c.execute("""
              UPDATE store_prices
              SET last_seen=?
              WHERE user_id=? AND store_id=? AND item_id=?
            """, (ts, user_id, store_id, item_id))

    conn.commit(); conn.close()
    clear_cart()
    return True, "Checkout complete. Inventory updated and purchases logged."


# --------------------------------
# UI
# --------------------------------
def shopping():
    st.title("🛒 Shopping")
    if "user_id" not in st.session_state:
        st.warning("Please login first")
        st.stop()
    user_id = st.session_state["user_id"]

    create_tables()
    run_shopping_migrations()
    _ensure_cart()

    # --- STORES ------------------------------------------------------------
    with st.expander("Stores & what they sell", expanded=False):
        col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 2, 2])
        new_name = col1.text_input("Store name")
        new_kind = col2.selectbox("Kind", ["local", "chain", "greengrocer", "online"])
        new_city = col3.text_input("City / Area", placeholder="optional")
        new_link = col4.text_input("Online link", placeholder="https://...")
        new_notes = col5.text_input("Notes", placeholder="opening hours, delivery etc.")
        if st.button("Add / Update store"):
            if new_name.strip():
                add_or_update_store(user_id, new_name, new_kind, new_city, new_link, new_notes)
                st.success("Store saved"); st.rerun()
            else:
                st.error("Store name is required")

        stores = get_stores(user_id)
        if stores:
            st.caption("Mark what each store sells:")
            for sid, sname, skind, scity, slink, snotes in stores:
                cats = get_store_categories(user_id, sid)
                with st.container():
                    cols = st.columns([2, 1, 2, 2, 1])
                    cols[0].markdown(f"**{sname}**  · _{skind}_  · {scity or ''}")
                    if slink: cols[2].markdown(f"[Open site]({slink})")
                    cols[3].write(snotes or "")
                    if cols[4].button("Delete", key=f"del_store_{sid}"):
                        delete_store(sid); st.warning("Store removed"); st.rerun()
                sel = st.multiselect(f"Categories for {sname}", FOOD_TYPES, default=cats, key=f"cats_{sid}")
                if st.button(f"Save categories for {sname}", key=f"save_cats_{sid}"):
                    set_store_categories(user_id, sid, sel); st.success("Saved")

        else:
            st.info("No stores yet — add one above.")

    # --- PRICE BOOK + QUICK BUY -------------------------------------------
    with st.expander("Price book (₪/base-unit) + quick buy", expanded=False):
        inv = get_inventory(user_id)
        stores_all = get_stores(user_id)
        if not stores_all:
            st.info("Add at least one store first.")
        else:
            # Existing inventory item -> price -> buy 1+ pack(s)
            cA, cB = st.columns([1.2, 2])
            # filter store by category of chosen item (when item chosen)
            item_sel = cB.selectbox("Inventory item", options=inv, format_func=lambda r: f"{r[1]} [{r[4]} · {r[2]}]")
            allowed_stores = stores_selling_type(user_id, item_sel[2]) or stores_all
            store_sel = cA.selectbox("Store", options=allowed_stores, format_func=lambda r: f"{r[1]} ({r[2]})", key="pb_store")

            p1, p2, p3, p4, p5 = st.columns([1, 1, 1, 1, 1.2])
            pack_qty = p1.number_input("Pack qty", min_value=0.0, step=0.1, value=1.0, key="pb_qty")
            pack_unit = p2.selectbox("Unit", UNITS, key="pb_unit")
            pack_price = p3.number_input("Pack price ₪", min_value=0.0, step=0.1, value=0.0, key="pb_price")
            packs_to_buy = p4.number_input("Buy packs", min_value=0, step=1, value=0, key="pb_buy")
            exp_opt = p5.date_input("Expiry (opt.)", value=date.today(), key="pb_exp")

            if st.button("Save price"):
                upsert_store_price(user_id, store_sel[0], item_sel[0], pack_qty, pack_unit, pack_price)
                st.success("Price saved")

            # Quick buy immediately adds to inventory
            if packs_to_buy > 0 and st.button("Buy now"):
                base_per_pack, base_unit = to_base(pack_qty, pack_unit)
                qty_base = base_per_pack * float(packs_to_buy)
                unit_price_base = (pack_price / base_per_pack) if base_per_pack > 0 else 0.0
                total_paid = float(packs_to_buy) * float(pack_price)
                _purchase_into_inventory(
                    user_id=user_id, item_id=item_sel[0],
                    qty_base=qty_base, unit_price_base=unit_price_base,
                    total_paid=total_paid, store_id=store_sel[0],
                    expiration=exp_opt.strftime("%Y-%m-%d") if exp_opt else None
                )
                upsert_store_price(user_id, store_sel[0], item_sel[0], pack_qty, pack_unit, pack_price)
                st.success("Purchased and added to inventory")

            # Show existing prices in this store
            st.divider()
            st.subheader(f"Prices at {store_sel[1]}")
            rows = get_store_prices_for_store(user_id, store_sel[0])
            if rows:
                for it_id, nm, typ, bu, pq, pu, pp, ppb, seen in rows:
                    cols = st.columns([3, 1.2, 1.2, 1.0, 1.2, 0.8])
                    cols[0].markdown(f"**{nm}** · [{typ}] · base={bu}")
                    cols[1].write(f"{pq:g} {pu} for ₪{pp:g}")
                    cols[2].write(f"₪{ppb:.2f} / {bu}")
                    buy_n = cols[3].number_input("packs", min_value=0, step=1, value=0, key=f"buy_{store_sel[0]}_{it_id}")
                    exp_line = cols[4].date_input("expiry", value=date.today(), key=f"exp_{store_sel[0]}_{it_id}")
                    if cols[5].button("Buy", key=f"buybtn_{store_sel[0]}_{it_id}"):
                        if buy_n > 0:
                            base_per_pack, _ = to_base(pq, pu)
                            qty_base = base_per_pack * float(buy_n)
                            unit_price_base = ppb
                            total_paid = float(buy_n) * float(pp)
                            _purchase_into_inventory(
                                user_id=user_id, item_id=it_id,
                                qty_base=qty_base, unit_price_base=unit_price_base,
                                total_paid=total_paid, store_id=store_sel[0],
                                expiration=exp_line.strftime("%Y-%m-%d") if exp_line else None
                            )
                            st.success("Purchased and added to inventory")
                        else:
                            st.error("Set packs > 0 to buy.")
            else:
                st.caption("No prices yet at this store.")

    # --- CREATE NEW ITEM FROM SHOPPING ------------------------------------
    with st.expander("Create a NEW item here (store + price + BUY now)", expanded=False):
        stores_all = get_stores(user_id)
        if not stores_all:
            st.info("Add a store first.")
        else:
            s1, s2 = st.columns([1.2, 2])
            store_sel = s1.selectbox("Store", options=stores_all, format_func=lambda r: f"{r[1]} ({r[2]})", key="ni_store")
            name = s2.text_input("Item name")
            typ = st.selectbox("Food type", FOOD_TYPES, key="ni_type")

            # Filter store by what it sells, show warning if mismatch
            cats = set(get_store_categories(user_id, store_sel[0]))
            if cats and typ not in cats:
                st.warning(f"⚠️ {store_sel[1]} is not marked as selling '{typ}'. You can still proceed, or add the category above.")

            c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1.4])
            base_unit = c1.selectbox("Base unit", ["pcs", "g", "ml"], index=0)
            pack_qty = c2.number_input("Pack qty", min_value=0.0, step=0.1, value=1.0, key="ni_qty")
            pack_unit = c3.selectbox("Pack unit", UNITS, key="ni_unit")
            pack_price = c4.number_input("Pack price ₪", min_value=0.0, step=0.1, value=0.0, key="ni_price")
            exp_buy = c5.date_input("Expiry (opt.)", value=date.today(), key="ni_exp")

            buy_packs = st.number_input("Buy packs now", min_value=1, step=1, value=1, key="ni_buy")
            if st.button("Create item as Stable + save price + BUY"):
                if not name.strip():
                    st.error("Name is required")
                else:
                    base_per_pack, bu_from_pack = to_base(pack_qty, pack_unit)
                    qty_base = base_per_pack * float(buy_packs)
                    unit_price_base = (pack_price / base_per_pack) if base_per_pack > 0 else 0.0
                    total_paid = float(buy_packs) * float(pack_price)

                    # create inventory item (Stable)
                    item_id = _insert_inventory_item_stable(
                        user_id=user_id, name=name.strip(), typ=typ,
                        qty_base=qty_base, base_unit=BASE_FOR.get(base_unit, "pcs"),
                        price_per_base=unit_price_base, total_cost=total_paid,
                        expiration=exp_buy.strftime("%Y-%m-%d") if exp_buy else None
                    )
                    # save price book linking this new item
                    upsert_store_price(user_id, store_sel[0], item_id, pack_qty, pack_unit, pack_price)
                    # and log purchase (already included in insert totals, but we keep consistent log)
                    _purchase_into_inventory(
                        user_id=user_id, item_id=item_id, qty_base=0.0,  # totals already set above
                        unit_price_base=unit_price_base, total_paid=0.0, store_id=store_sel[0],
                        expiration=None
                    )
                    st.success("Created item (Stable), saved price, and purchased into inventory.")

    # --- STOCK RULES (Always-buy & Par) -----------------------------------
    with st.expander("Stock rules (Always-buy & Par levels)", expanded=False):
        inv = get_inventory(user_id)
        if not inv:
            st.info("Inventory is empty.")
        else:
            for (iid, nm, typ, kind, bu, onhand, ppb, always_buy, par, stable_flag) in inv:
                cols = st.columns([2.2, 1.2, 1.2, 1])
                cols[0].write(f"**{nm}**  _[{typ} · {bu}]_ — on hand: {onhand:.1f} {bu}")
                ab = cols[1].checkbox("Always buy", value=bool(always_buy), key=f"ab_{iid}")
                new_par = cols[2].number_input("Par (base)", min_value=0.0, step=step_size_for(bu), value=float(par or 0.0), key=f"par_{iid}")
                if cols[3].button("Save", key=f"sv_{iid}"):
                    set_item_rules(iid, ab, new_par); st.success("Rules saved")

    # --- MAP STABLE ITEMS TO STORES ---------------------------------------
    with st.expander("Map stable items to stores (add prices fast)", expanded=False):
        inv = [r for r in get_inventory(user_id) if r[-1] == 1]  # stable==1
        if not inv:
            st.info("No stable items yet.")
        else:
            left, right = st.columns([1.6, 2])
            irow = left.selectbox("Stable item", options=inv, format_func=lambda r: f"{r[1]} [{r[2]} · {r[4]}]")
            stores_ok = stores_selling_type(user_id, irow[2]) or get_stores(user_id)
            srow = left.selectbox("Store", options=stores_ok, format_func=lambda r: f"{r[1]} ({r[2]})", key="map_store")
            pq, pu, price = right.columns([1,1,1])
            pack_qty = pq.number_input("Pack qty", min_value=0.0, step=0.1, value=1.0, key="map_qty")
            pack_unit = pu.selectbox("Unit", UNITS, key="map_unit")
            pack_price = price.number_input("Pack price ₪", min_value=0.0, step=0.1, value=0.0, key="map_price")
            if st.button("Save price mapping"):
                upsert_store_price(user_id, srow[0], irow[0], pack_qty, pack_unit, pack_price)
                st.success("Price saved for this store")

    # --- AI LIST BUILDER ---------------------------------------------------
    st.subheader("✨ AI shopping suggestions")
    col_a, col_b, col_c = st.columns([1,1,2])
    target_days = col_a.number_input("Target coverage (days)", min_value=3, max_value=60, value=14, step=1)
    threshold = col_b.number_input("Suggest when stock < days", min_value=1, max_value=30, value=7, step=1)
    if col_c.button("Build suggestions"):
        st.session_state.suggestions = suggest_shopping_lines(user_id, target_days, threshold)
    if "suggestions" in st.session_state and st.session_state.suggestions:
        for idx, row in enumerate(st.session_state.suggestions):
            c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1.6, 1.2, 1.2, 1])
            c1.write(f"**{row['name']}** [{row['type']} · {row['base_unit']}]")
            qty = c2.number_input("Qty (base)", min_value=0.0, step=step_size_for(row["base_unit"]),
                                  value=float(row["qty_base"]), key=f"sugg_qty_{idx}")
            # stores that sell this type
            stores_ok = stores_selling_type(user_id, row["type"]) or get_stores(user_id)
            store_id = row["store_id"]
            chosen = c3.selectbox("Store", options=[(None,"—","","","")]+stores_ok,
                                  index=0 if store_id is None else 1 + next((i for i,s in enumerate(stores_ok) if s[0]==store_id), 0),
                                  format_func=lambda r: r[1] if isinstance(r, tuple) else "—",
                                  key=f"sugg_store_{idx}")
            unit_price = c4.number_input("₪/base", min_value=0.0, step=0.1,
                                         value=float(row["unit_price_base"] or 0.0), key=f"sugg_ppb_{idx}")
            exp = c5.date_input("Expiry (opt.)", value=date.today(), key=f"sugg_exp_{idx}")
            if c6.button("Add to cart", key=f"sugg_add_{idx}"):
                add_to_cart({
                    "item_id": row["item_id"], "name": row["name"], "base_unit": row["base_unit"],
                    "qty_base": float(qty),
                    "store_id": None if chosen[0] is None else chosen[0],
                    "store_name": None if chosen[0] is None else chosen[1],
                    "unit_price_base": float(unit_price),
                    "expiration": exp.strftime("%Y-%m-%d") if exp else None,
                })
                st.success("Added to cart")

    # --- QUICK ADD TO CART -------------------------------------------------
    with st.expander("Quick add to cart", expanded=False):
        inv = get_inventory(user_id)
        stores_all = get_stores(user_id)
        if inv:
            irow = st.selectbox("Item", options=inv, format_func=lambda r: f"{r[1]} [{r[2]} · {r[4]}]")
            step = step_size_for(irow[4])
            qa, qb, qc, qd = st.columns([1, 1.6, 1.2, 1.2])
            qty = qa.number_input("Qty (base)", min_value=0.0, step=step, value=step)
            stores_ok = stores_selling_type(user_id, irow[2]) or stores_all
            s = qb.selectbox("Store", options=[(None,"—","","","")]+stores_ok, format_func=lambda r: r[1] if isinstance(r, tuple) else "—")
            ppb = qc.number_input("₪/base", min_value=0.0, step=0.1, value=float(irow[6] or 0.0))
            exp = qd.date_input("Expiry (opt.)", value=date.today())
            if st.button("Add"):
                add_to_cart({
                    "item_id": irow[0], "name": irow[1], "base_unit": irow[4],
                    "qty_base": float(qty),
                    "store_id": None if s[0] is None else s[0],
                    "store_name": None if s[0] is None else s[1],
                    "unit_price_base": float(ppb),
                    "expiration": exp.strftime("%Y-%m-%d") if exp else None,
                })
                st.success("Added to cart")

    # --- CART --------------------------------------------------------------
    st.subheader("🧺 Cart")
    if not st.session_state.cart:
        st.info("Cart is empty.")
    else:
        totals_by_store: Dict[Optional[int], float] = {}
        for idx, row in enumerate(st.session_state.cart):
            unit_total = float(row.get("unit_price_base") or 0.0) * float(row["qty_base"])
            store_key = row.get("store_id")
            totals_by_store[store_key] = totals_by_store.get(store_key, 0.0) + unit_total

            c1, c2, c3, c4, c5, c6, c7 = st.columns([2, 1, 1.2, 1.6, 1.2, 1.2, 0.8])
            c1.write(f"**{row['name']}** [{row['base_unit']}]")
            row["qty_base"] = c2.number_input("Qty (base)", min_value=0.0, step=step_size_for(row["base_unit"]),
                                              value=float(row["qty_base"]), key=f"cart_qty_{idx}")
            row["unit_price_base"] = c3.number_input("₪/base", min_value=0.0, step=0.1,
                                                     value=float(row.get("unit_price_base") or 0.0), key=f"cart_ppb_{idx}")
            # filter stores by category (we don't have type here, so leave all to avoid hidden mismatch)
            stores = get_stores(user_id)
            store_opts = [(None, "—", "", "", "")] + stores
            cur_index = 0 if row.get("store_id") is None else 1 + next((i for i,s in enumerate(stores) if s[0]==row["store_id"]), 0)
            chosen = c4.selectbox("Store", options=store_opts, index=cur_index, format_func=lambda r: r[1] if isinstance(r, tuple) else "—", key=f"cart_store_{idx}")
            row["store_id"] = None if chosen[0] is None else chosen[0]
            row["store_name"] = None if chosen[0] is None else chosen[1]
            exp_val = row.get("expiration")
            row["expiration"] = c5.date_input("Expiry (opt.)", value=date.fromisoformat(exp_val) if exp_val else date.today(), key=f"cart_exp_{idx}").strftime("%Y-%m-%d")
            c6.write(f"Line: ₪{row['unit_price_base'] * row['qty_base']:.2f}")
            if c7.button("✕", key=f"rm_{idx}"):
                remove_from_cart(idx); st.rerun()

        st.divider()
        for sid, total in totals_by_store.items():
            store_name = "No store" if sid is None else next((s[1] for s in get_stores(user_id) if s[0]==sid), "Store")
            st.write(f"**{store_name}** — ₪{total:.2f}")
        st.write(f"**Grand total: ₪{sum(totals_by_store.values()):.2f}**")

        colx, coly, colz = st.columns([1,1,2])
        if colx.button("Clear cart"):
            clear_cart(); st.rerun()
        if coly.button("Checkout"):
            ok, msg = checkout_cart(user_id)
            st.success(msg) if ok else st.error(msg)
            st.rerun()

    # --- SAVE / LOAD LISTS (unchanged) ------------------------------------
    with st.expander("Save / Load lists", expanded=False):
        title = st.text_input("List title")
        if st.button("Save current cart as template"):
            if not st.session_state.cart:
                st.error("Cart is empty")
            elif not title.strip():
                st.error("Title is required")
            else:
                conn = get_connection(); c = conn.cursor()
                c.execute("INSERT INTO shopping_lists(user_id, title, status, created_at) VALUES (?,?, 'template', ?)",
                          (user_id, title.strip(), iso_today()))
                list_id = c.lastrowid
                for row in st.session_state.cart:
                    c.execute("""
                      INSERT INTO shopping_list_items(list_id, item_id, desired_qty_base, chosen_store_id, est_unit_price_base, est_total, expiration)
                      VALUES (?,?,?,?,?,?,?)
                    """, (list_id, row["item_id"], row["qty_base"], row.get("store_id"), row.get("unit_price_base"),
                          (row.get("unit_price_base") or 0.0) * row["qty_base"], row.get("expiration")))
                conn.commit(); conn.close()
                st.success("Saved as template")

        conn = get_connection(); c = conn.cursor()
        c.execute("SELECT id, title, created_at FROM shopping_lists WHERE user_id=? AND status='template' ORDER BY created_at DESC", (user_id,))
        templates = c.fetchall(); conn.close()
        if templates:
            chosen = st.selectbox("Load template", options=templates, format_func=lambda r: f"{r[1]} ({r[2]})")
            if st.button("Load → cart"):
                conn = get_connection(); c = conn.cursor()
                c.execute("""SELECT item_id, desired_qty_base, chosen_store_id, est_unit_price_base, expiration
                            FROM shopping_list_items WHERE list_id=?""", (chosen[0],))
                rows = c.fetchall(); conn.close()
                clear_cart()
                inv = get_inventory(user_id)
                for item_id, qty, store_id, unit_ppb, exp in rows:
                    meta = next((r for r in inv if r[0]==item_id), None)
                    if not meta:
                        continue
                    add_to_cart({
                        "item_id": item_id, "name": meta[1], "base_unit": meta[4],
                        "qty_base": float(qty or 0.0),
                        "store_id": store_id, "store_name": None,
                        "unit_price_base": float(unit_ppb or 0.0),
                        "expiration": exp,
                    })
                st.success("Template loaded to cart")

# Entry point for router
def app():
    shopping()

if __name__ == "__main__":
    shopping()
