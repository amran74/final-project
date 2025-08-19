# Shopping.py — Stores, price book, AI list builder, cart & checkout
# Works with your Inventory/DB: adds store + price + shopping tables,
# suggests a list from usage patterns, supports always-buy & par levels,
# groups cart by store, updates inventory & logs purchases on checkout.

import streamlit as st
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple
import math

from db import (
    get_connection,
    create_tables,
    _today_keys,   # not used directly here but kept for parity with the project
)

# -------------------------
# Shared unit helpers (mirror Inventory)
# -------------------------

UNITS = ["pcs", "g", "kg", "mg", "ml", "l"]
BASE_FOR = {"pcs": "pcs", "g": "g", "kg": "g", "mg": "g", "ml": "ml", "l": "ml"}
MULTIPLIER_TO_BASE = {"pcs": 1.0, "mg": 0.001, "g": 1.0, "kg": 1000.0, "ml": 1.0, "l": 1000.0}

def to_base(amount: float, unit: str) -> Tuple[float, str]:
    unit = (unit or "pcs").lower()
    if unit not in BASE_FOR:
        return float(amount), "pcs"
    return float(amount) * MULTIPLIER_TO_BASE[unit], BASE_FOR[unit]

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

# -------------------------
# Migrations (shopping + a few inventory helpers)
# -------------------------

SHOP_MIGRATIONS = [
    ("""
    CREATE TABLE IF NOT EXISTS stores (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      name TEXT NOT NULL,
      kind TEXT DEFAULT 'local',            -- local | chain | greengrocer | online
      city TEXT,
      link_url TEXT,
      notes TEXT,
      UNIQUE(user_id, name)
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
      UNIQUE(user_id, store_id, item_id)
    )
    """,),
    ("""
    CREATE TABLE IF NOT EXISTS shopping_lists (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL,
      title TEXT NOT NULL,
      status TEXT DEFAULT 'draft',          -- draft | purchased | template
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
    ("ALTER TABLE inventory ADD COLUMN always_buy INTEGER DEFAULT 0",),
    ("ALTER TABLE inventory ADD COLUMN par_level_base REAL DEFAULT 0.0",),
]

def run_shopping_migrations():
    conn = get_connection()
    c = conn.cursor()
    # discover inventory columns to avoid duplicate ALTERs
    c.execute("PRAGMA table_info(inventory)")
    inv_cols = {row[1] for row in c.fetchall()}
    for mig in SHOP_MIGRATIONS:
        stmt = mig[0]
        try:
            if stmt.startswith("ALTER TABLE inventory"):
                col = stmt.split(" ADD COLUMN ")[1].split(" ")[0]
                if col in inv_cols:
                    continue
            c.execute(stmt)
            conn.commit()
        except Exception:
            # ignore if already applied / harmless
            pass
    conn.close()

# -------------------------
# Data access helpers
# -------------------------

def get_inventory(user_id: int) -> List[tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, name, type, kind, base_unit, base_amount, price_per_base, always_buy, COALESCE(par_level_base,0)
      FROM inventory
      WHERE user_id=?
      ORDER BY name
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_stores(user_id: int) -> List[tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, name, kind, city, link_url, COALESCE(notes,'')
      FROM stores
      WHERE user_id=?
      ORDER BY kind, name
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def add_or_update_store(user_id: int, name: str, kind: str, city: str, link_url: str, notes: str):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      INSERT INTO stores(user_id, name, kind, city, link_url, notes)
      VALUES (?,?,?,?,?,?)
      ON CONFLICT(user_id, name) DO UPDATE SET
        kind=excluded.kind, city=excluded.city, link_url=excluded.link_url, notes=excluded.notes
    """, (user_id, name.strip(), kind, city.strip() if city else None,
          link_url.strip() if link_url else None, notes.strip() if notes else None))
    conn.commit(); conn.close()

def delete_store(store_id: int):
    conn = get_connection(); c = conn.cursor()
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
    """, (user_id, store_id, item_id, float(pack_qty), pack_unit, float(pack_price),
          float(price_per_base), iso_today()))
    conn.commit(); conn.close()

def get_store_prices_for_store(user_id: int, store_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT sp.item_id, i.name, i.base_unit, sp.pack_qty, sp.pack_unit, sp.pack_price, sp.price_per_base, sp.last_seen
      FROM store_prices sp
      JOIN inventory i ON i.id = sp.item_id
      WHERE sp.user_id=? AND sp.store_id=?
      ORDER BY i.name
    """, (user_id, store_id))
    rows = c.fetchall()
    conn.close()
    return rows

def best_price_for_item(user_id: int, item_id: int) -> Optional[tuple]:
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT sp.store_id, s.name, sp.price_per_base
      FROM store_prices sp
      JOIN stores s ON s.id = sp.store_id
      WHERE sp.user_id=? AND sp.item_id=?
      ORDER BY sp.price_per_base ASC
      LIMIT 1
    """, (user_id, item_id))
    row = c.fetchone()
    conn.close()
    return row

def set_item_rules(item_id: int, always_buy: bool, par_level_base: float):
    conn = get_connection()
    conn.execute("UPDATE inventory SET always_buy=?, par_level_base=? WHERE id=?",
                 (1 if always_buy else 0, float(par_level_base or 0.0), item_id))
    conn.commit(); conn.close()

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

# -------------------------
# Smart list builder
# -------------------------

def suggest_shopping_lines(user_id: int,
                           target_days: int = 14,
                           coverage_threshold_days: int = 7) -> List[Dict]:
    inv = get_inventory(user_id)
    lines = []
    for (item_id, name, typ, kind, base_unit, on_hand, ppb, always_buy, par_base) in inv:
        on_hand = float(on_hand or 0.0)
        par_base = float(par_base or 0.0)
        avg_daily = recent_daily_usage_base(user_id, item_id, base_unit)
        coverage_days = (on_hand / avg_daily) if avg_daily > 0 else 9e9

        include = False
        desired = 0.0

        if always_buy:
            include = True
            desired = max(par_base - on_hand, 0.0) if par_base > 0 else 0.0
            if desired <= 0:
                desired = step_size_for(base_unit)
        elif coverage_days < coverage_threshold_days:
            include = True
            target_qty = max(target_days * avg_daily - on_hand, 0.0)
            step = step_size_for(base_unit)
            desired = math.ceil(target_qty / step) * step

        if include and desired > 0.0:
            bp = best_price_for_item(user_id, item_id)
            store_id, store_name, ppb_best = (bp if bp else (None, None, float(ppb or 0.0)))
            est_total = float(ppb_best or 0.0) * desired
            lines.append({
                "item_id": item_id,
                "name": name,
                "type": typ,
                "base_unit": base_unit,
                "qty_base": round(desired, 2),
                "store_id": store_id,
                "store_name": store_name,
                "unit_price_base": float(ppb_best or 0.0),
                "est_total": round(est_total, 2),
                "suggested": True,
                "expiration": None,
            })
    return lines

# -------------------------
# Cart (Session)
# -------------------------

def _ensure_cart():
    if "cart" not in st.session_state:
        st.session_state.cart = []

def add_to_cart(row: Dict):
    _ensure_cart()
    st.session_state.cart.append(row)

def remove_from_cart(idx: int):
    _ensure_cart()
    if 0 <= idx < len(st.session_state.cart):
        del st.session_state.cart[idx]

def clear_cart():
    st.session_state.cart = []

# -------------------------
# Checkout: write to DB & update inventory
# -------------------------

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

        # Update inventory (increase base_amount & moving average price)
        c.execute("SELECT base_amount, total_cost, price_per_base FROM inventory WHERE id=?", (item_id,))
        cur = c.fetchone()
        if not cur:
            continue
        base_amount, total_cost, old_ppb = cur
        base_amount = float(base_amount or 0.0)
        total_cost = float(total_cost or 0.0)
        new_base_amount = base_amount + qty_base
        new_total_cost = total_cost + total_paid
        new_ppb = (new_total_cost / new_base_amount) if new_base_amount > 0 else (old_ppb or unit_price_base)

        if exp:
            c.execute("""
              UPDATE inventory
                 SET base_amount=?, total_cost=?, price_per_base=?, expiration=?, stable=1
               WHERE id=?
            """, (new_base_amount, new_total_cost, new_ppb, exp, item_id))
        else:
            c.execute("""
              UPDATE inventory
                 SET base_amount=?, total_cost=?, price_per_base=?, stable=1
               WHERE id=?
            """, (new_base_amount, new_total_cost, new_ppb, item_id))

        # Log purchase
        c.execute("""
          INSERT INTO purchases_log(user_id, item_id, store_id, qty_base, unit_price_base, total_paid, ts)
          VALUES (?,?,?,?,?,?,?)
        """, (user_id, item_id, store_id, qty_base, unit_price_base, total_paid, ts))

        # Touch price book last_seen if price existed
        if store_id is not None and unit_price_base > 0:
            c.execute("""
              UPDATE store_prices
                 SET last_seen=?
               WHERE user_id=? AND store_id=? AND item_id=?
            """, (ts, user_id, store_id, item_id))

    conn.commit(); conn.close()
    clear_cart()
    return True, "Checkout complete. Inventory updated and purchases logged."

# -------------------------
# UI
# -------------------------

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
    with st.expander("Stores", expanded=False):
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
            st.caption("Your stores")
            for sid, sname, skind, scity, slink, snotes in stores:
                cols = st.columns([2,1,1.2,2,2,1])
                cols[0].write(f"**{sname}**")
                cols[1].write(skind)
                cols[2].write(scity or "")
                cols[3].markdown(f"[Open site]({slink})" if slink else "—")
                cols[4].write(snotes or "")
                if cols[5].button("Delete", key=f"del_store_{sid}"):
                    delete_store(sid); st.warning("Store removed"); st.rerun()
        else:
            st.info("No stores yet — add one above.")

    # --- PRICE BOOK --------------------------------------------------------
    with st.expander("Price book (₪/base-unit)", expanded=False):
        inv = get_inventory(user_id)
        stores = get_stores(user_id)
        if not stores or not inv:
            st.info("Add at least one store and one inventory item to record prices.")
        else:
            c1, c2 = st.columns([1.2, 2])
            store_sel = c1.selectbox("Store", options=stores,
                                     format_func=lambda r: f"{r[1]} ({r[2]})", key="pb_store")
            item_sel = c2.selectbox("Item", options=inv,
                                    format_func=lambda r: f"{r[1]} [{r[4]}]", key="pb_item")
            p1, p2, p3 = st.columns([1, 1, 1])
            pack_qty = p1.number_input("Pack qty", min_value=0.0, step=0.1, value=1.0, key="pb_qty")
            pack_unit = p2.selectbox("Unit", UNITS, key="pb_unit")
            pack_price = p3.number_input("Pack price ₪", min_value=0.0, step=0.1, value=0.0, key="pb_price")
            if st.button("Save price"):
                upsert_store_price(user_id, store_sel[0], item_sel[0], pack_qty, pack_unit, pack_price)
                st.success("Price saved"); st.rerun()

            if store_sel:
                st.subheader(f"Prices at {store_sel[1]}")
                rows = get_store_prices_for_store(user_id, store_sel[0])
                if rows:
                    for it_id, nm, bu, pq, pu, pp, ppb, seen in rows:
                        st.write(f"{nm} – {pq:g} {pu} for ₪{pp:g} → **₪{ppb:.2f} / {bu}**  (seen {seen})")
                else:
                    st.caption("No prices yet at this store.")

    # --- STOCK RULES (Always-buy & Par) -----------------------------------
    with st.expander("Stock rules (Always-buy & Par levels)", expanded=False):
        inv = get_inventory(user_id)
        if not inv:
            st.info("Inventory is empty.")
        else:
            for (iid, nm, typ, kind, bu, onhand, ppb, always_buy, par) in inv:
                cols = st.columns([2, 1, 1.2, 1.2, 1])
                cols[0].write(f"**{nm}**  _[{bu}]_  — on hand: {onhand:.1f} {bu}")
                ab = cols[1].checkbox("Always buy", value=bool(always_buy), key=f"ab_{iid}")
                new_par = cols[2].number_input("Par (base)", min_value=0.0, step=step_size_for(bu),
                                               value=float(par or 0.0), key=f"par_{iid}")
                if cols[3].button("Save", key=f"sv_{iid}"):
                    set_item_rules(iid, ab, new_par); st.success("Rules saved")

    # --- AI LIST BUILDER ---------------------------------------------------
    st.subheader("✨ AI shopping suggestions")
    col_a, col_b, col_c = st.columns([1,1,2])
    target_days = col_a.number_input("Target coverage (days)", min_value=3, max_value=60, value=14, step=1)
    threshold = col_b.number_input("Suggest when stock < days", min_value=1, max_value=30, value=7, step=1)
    if col_c.button("Build suggestions"):
        st.session_state.suggestions = suggest_shopping_lines(user_id, target_days, threshold)
    if "suggestions" in st.session_state and st.session_state.suggestions:
        for idx, row in enumerate(st.session_state.suggestions):
            c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1.2, 1.6, 1, 1])
            c1.write(f"**{row['name']}** [{row['base_unit']}]")
            qty = c2.number_input("Qty (base)", min_value=0.0, step=step_size_for(row["base_unit"]),
                                  value=float(row["qty_base"]), key=f"sugg_qty_{idx}")
            store_id = row["store_id"]
            stores = get_stores(user_id)
            store_options = [(None, "— No store —", "", "", "")] + stores
            idx_default = 0 if store_id is None else 1 + next((i for i,s in enumerate(stores) if s[0]==store_id), 0)
            chosen = c3.selectbox("Store", options=store_options, index=idx_default,
                                  format_func=lambda r: r[1] if isinstance(r, tuple) else "—",
                                  key=f"sugg_store_{idx}")
            unit_price = c4.number_input("₪/base", min_value=0.0, step=0.1,
                                         value=float(row["unit_price_base"] or 0.0), key=f"sugg_ppb_{idx}")
            exp = c5.date_input("Expiry (opt.)", value=date.today(), key=f"sugg_exp_{idx}")
            if c6.button("Add to cart", key=f"sugg_add_{idx}"):
                add_to_cart({
                    "item_id": row["item_id"],
                    "name": row["name"],
                    "base_unit": row["base_unit"],
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
        stores = get_stores(user_id)
        if inv:
            irow = st.selectbox("Item", options=inv, format_func=lambda r: f"{r[1]} [{r[4]}]")
            step = step_size_for(irow[4])
            qa, qb, qc, qd = st.columns([1, 1, 1.2, 1.2])
            qty = qa.number_input("Qty (base)", min_value=0.0, step=step, value=step)
            s = qb.selectbox("Store", options=[(None, "—", "", "", "")]+stores,
                             format_func=lambda r: r[1] if isinstance(r, tuple) else "—")
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
            line_total = float(row.get("unit_price_base") or 0.0) * float(row["qty_base"])
            store_key = row.get("store_id")
            totals_by_store[store_key] = totals_by_store.get(store_key, 0.0) + line_total

            c1, c2, c3, c4, c5, c6, c7 = st.columns([2, 1, 1.2, 1.2, 1.4, 1.2, 0.8])
            c1.write(f"**{row['name']}** [{row['base_unit']}]")
            row["qty_base"] = c2.number_input("Qty (base)", min_value=0.0,
                                              step=step_size_for(row["base_unit"]),
                                              value=float(row["qty_base"]), key=f"cart_qty_{idx}")
            row["unit_price_base"] = c3.number_input("₪/base", min_value=0.0, step=0.1,
                                                     value=float(row.get("unit_price_base") or 0.0),
                                                     key=f"cart_ppb_{idx}")
            stores = get_stores(user_id)
            store_opts = [(None, "—", "", "", "")] + stores
            cur_index = 0 if row.get("store_id") is None else 1 + next((i for i,s in enumerate(stores) if s[0]==row["store_id"]), 0)
            chosen = c4.selectbox("Store", options=store_opts, index=cur_index,
                                  format_func=lambda r: r[1] if isinstance(r, tuple) else "—",
                                  key=f"cart_store_{idx}")
            row["store_id"] = None if chosen[0] is None else chosen[0]
            row["store_name"] = None if chosen[0] is None else chosen[1]
            exp_val = row.get("expiration")
            row["expiration"] = c5.date_input("Expiry (opt.)",
                                              value=date.fromisoformat(exp_val) if exp_val else date.today(),
                                              key=f"cart_exp_{idx}").strftime("%Y-%m-%d")
            c6.write(f"Line: ₪{row['unit_price_base'] * row['qty_base']:.2f}")
            if c7.button("✕", key=f"rm_{idx}"):
                remove_from_cart(idx); st.rerun()

        st.divider()
        for sid, total in totals_by_store.items():
            name = "No store"
            if sid is not None:
                store = next((s for s in get_stores(user_id) if s[0] == sid), None)
                name = store[1] if store else "Store"
            st.write(f"**{name}** — ₪{total:.2f}")
        st.write(f"**Grand total: ₪{sum(totals_by_store.values()):.2f}**")

        colx, coly, colz = st.columns([1,1,2])
        if colx.button("Clear cart"):
            clear_cart(); st.rerun()
        if coly.button("Checkout"):
            ok, msg = checkout_cart(user_id)
            st.success(msg) if ok else st.error(msg)
            st.rerun()

    # --- SAVE CART AS LIST (template) --------------------------------------
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
                    """, (list_id, row["item_id"], row["qty_base"], row.get("store_id"),
                          row.get("unit_price_base"),
                          (row.get("unit_price_base") or 0.0) * row["qty_base"], row.get("expiration")))
                conn.commit(); conn.close()
                st.success("Saved as template")

        conn = get_connection(); c = conn.cursor()
        c.execute("SELECT id, title, created_at FROM shopping_lists WHERE user_id=? AND status='template' ORDER BY created_at DESC", (user_id,))
        templates = c.fetchall(); conn.close()
        if templates:
            chosen = st.selectbox("Load template", options=templates,
                                  format_func=lambda r: f"{r[1]} ({r[2]})")
            if st.button("Load → cart"):
                conn = get_connection(); c = conn.cursor()
                c.execute("""
                  SELECT item_id, desired_qty_base, chosen_store_id, est_unit_price_base, expiration
                    FROM shopping_list_items
                   WHERE list_id=?
                """, (chosen[0],))
                rows = c.fetchall(); conn.close()
                clear_cart()
                inv = get_inventory(user_id)
                for item_id, qty, store_id, unit_ppb, exp in rows:
                    meta = next((r for r in inv if r[0] == item_id), None)
                    if not meta:
                        continue
                    add_to_cart({
                        "item_id": item_id,
                        "name": meta[1],
                        "base_unit": meta[4],
                        "qty_base": float(qty or 0.0),
                        "store_id": store_id,
                        "store_name": None,
                        "unit_price_base": float(unit_ppb or 0.0),
                        "expiration": exp,
                    })
                st.success("Template loaded to cart")

# entrypoint used by your multipage app router
def app():
    shopping()

if __name__ == "__main__":
    shopping()
