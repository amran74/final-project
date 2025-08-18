# Inventory.py — full upgrade: ingredients + prepared, recipes, batches, frozen state, base units, smart pricing, filters, export
import streamlit as st
from datetime import datetime, date, timedelta
from typing import Tuple, Optional, List
import csv
import io

# import db helpers you already have
from db import (
    get_connection,
    create_tables,
)

# -------------------------
# Utilities
# -------------------------

UNITS = ["pcs", "g", "kg", "mg", "ml", "l"]
BASE_FOR = {"pcs": "pcs", "g": "g", "kg": "g", "mg": "g", "ml": "ml", "l": "ml"}
MULTIPLIER_TO_BASE = {"pcs": 1.0, "mg": 0.001, "g": 1.0, "kg": 1000.0, "ml": 1.0, "l": 1000.0}

def to_base(amount: float, unit: str) -> Tuple[float, str]:
    if unit not in BASE_FOR:
        return amount, "pcs"
    return amount * MULTIPLIER_TO_BASE[unit], BASE_FOR[unit]

def from_base(amount_base: float, ui_unit: str) -> float:
    if ui_unit == "kg":
        return amount_base / 1000.0
    if ui_unit == "g":
        return amount_base
    if ui_unit == "mg":
        return amount_base * 1000.0
    if ui_unit == "l":
        return amount_base / 1000.0
    if ui_unit == "ml":
        return amount_base
    return amount_base

def format_price_hint(ui_unit: str, price_per_base: float) -> Tuple[str, str]:
    if ui_unit in ["kg", "g", "mg"]:
        return f"{price_per_base * 100:.2f}", "per 100 g"
    if ui_unit in ["l", "ml"]:
        return f"{price_per_base * 100:.2f}", "per 100 ml"
    return f"{price_per_base:.2f}", "per piece"

def compute_price_per_base(total_cost: float, base_amount: float) -> float:
    if base_amount <= 0:
        return 0.0
    return total_cost / base_amount

def parse_iso(d: str) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date()

def today() -> date:
    return date.today()

def iso_today() -> str:
    return today().strftime("%Y-%m-%d")

def safely_execute(conn, sql, params=()):
    c = conn.cursor()
    c.execute(sql, params)
    conn.commit()

# -------------------------
# One time migrations
# -------------------------

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
    # recipe tables
    ("CREATE TABLE IF NOT EXISTS recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, prepared_item_id INTEGER NOT NULL UNIQUE)",),
    ("CREATE TABLE IF NOT EXISTS recipe_components (id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id INTEGER NOT NULL, ingredient_item_id INTEGER NOT NULL, quantity_base REAL NOT NULL, UNIQUE(recipe_id, ingredient_item_id))",),
    # simple batches for prepared food
    ("CREATE TABLE IF NOT EXISTS batches (id INTEGER PRIMARY KEY AUTOINCREMENT, prepared_item_id INTEGER NOT NULL, cooked_at TEXT NOT NULL, total_yield_base REAL NOT NULL, portion_size_base REAL NOT NULL, remaining_base REAL NOT NULL, expiration TEXT, storage_state TEXT DEFAULT 'fresh', frozen_at TEXT, thawed_at TEXT, frozen_days_accum INTEGER DEFAULT 0, batch_cost REAL)",),
]

def run_migrations():
    conn = get_connection()
    c = conn.cursor()
    c.execute("PRAGMA table_info(inventory)")
    cols = {row[1] for row in c.fetchall()}
    for mig in MIGRATIONS:
        stmt = mig[0]
        if stmt.startswith("CREATE TABLE"):
            try:
                c.execute(stmt); conn.commit()
            except Exception:
                pass
            continue
        target_col = stmt.split(" ADD COLUMN ")[1].split(" ")[0]
        if target_col not in cols:
            try:
                c.execute(stmt); conn.commit(); cols.add(target_col)
            except Exception:
                pass
    conn.close()

# -------------------------
# Expiration with frozen pause
# -------------------------

def effective_expiration(expiration: str, storage_state: str, frozen_at: Optional[str], thawed_at: Optional[str], frozen_days_accum: int) -> date:
    base_exp = parse_iso(expiration)
    paused_days = frozen_days_accum
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
    if delta < 0:
        return "Expired", "#FF4B4B"
    if delta <= 2:
        return "Expiring Soon", "#FFA500"
    return "Fresh", "#4CAF50"

# -------------------------
# Data access
# -------------------------

def add_item(
    user_id: int,
    name: str,
    expiration: str,
    food_type: str,
    ui_amount: float,
    ui_unit: str,
    total_cost: float,
    kind: str,
    stable: bool,
    recipe_note: Optional[str],
    thaw_shelf_life_days: Optional[int]
):
    base_amount, base_unit = to_base(ui_amount, ui_unit)
    price_per_base = compute_price_per_base(total_cost, base_amount)
    conn = get_connection()
    safely_execute(conn, """
        INSERT INTO inventory
        (user_id, name, expiration, type, amount, unit, used_count, last_used_month, stable,
         price_per_unit, expired_count, money_lost,
         kind, base_unit, base_amount, total_cost, price_per_base,
         storage_state, frozen_at, thawed_at, frozen_days_accum, thaw_shelf_life_days, recipe_note)
        VALUES (?, ?, ?, ?, ?, ?, 0, strftime('%Y-%m','now'), ?, 0.0, 0, 0.0,
                ?, ?, ?, ?, ?, 'fresh', NULL, NULL, 0, ?, ?)
    """, (
        user_id, name, expiration, food_type, ui_amount, ui_unit, int(stable),
        kind, base_unit, base_amount, total_cost, price_per_base,
        thaw_shelf_life_days, recipe_note
    ))
    conn.close()

def get_user_items(user_id: int):
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
    rows = c.fetchall()
    conn.close()
    return rows

def delete_item(item_id: int):
    conn = get_connection()
    safely_execute(conn, "DELETE FROM inventory WHERE id=?", (item_id,))
    conn.close()

def update_item(item_id: int, name: str, expiration: str, food_type: str,
                ui_amount: float, ui_unit: str, total_cost: float,
                kind: str, thaw_shelf_life_days: Optional[int], recipe_note: Optional[str]):
    base_amount, base_unit = to_base(ui_amount, ui_unit)
    price_per_base = compute_price_per_base(total_cost, base_amount)
    conn = get_connection()
    safely_execute(conn, """
        UPDATE inventory
        SET name=?, expiration=?, type=?, amount=?, unit=?, total_cost=?, price_per_base=?,
            base_amount=?, base_unit=?, kind=?, thaw_shelf_life_days=?, recipe_note=?
        WHERE id=?
    """, (name, expiration, food_type, ui_amount, ui_unit, total_cost, price_per_base,
          base_amount, base_unit, kind, thaw_shelf_life_days, recipe_note, item_id))
    conn.close()

def use_quantity(item_id: int, qty_ui: float, ui_unit: str) -> Tuple[bool, str]:
    base_qty, _ = to_base(qty_ui, ui_unit)
    if base_qty <= 0:
        return False, "Quantity must be positive"
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT base_amount, storage_state FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close(); return False, "Item not found"
    base_amount, storage_state = row
    if storage_state == "frozen":
        conn.close(); return False, "Cannot use while frozen. Thaw first."
    new_amount = max(0.0, float(base_amount) - base_qty)
    c.execute("UPDATE inventory SET base_amount=? WHERE id=?", (new_amount, item_id))
    conn.commit(); conn.close()
    return True, f"Used {qty_ui} {ui_unit}"

def expire_quantity(item_id: int, qty_ui: float, ui_unit: str) -> Tuple[bool, str]:
    base_qty, _ = to_base(qty_ui, ui_unit)
    if base_qty <= 0:
        return False, "Quantity must be positive"
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT base_amount, price_per_base FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close(); return False, "Item not found"
    base_amount, price_per_base = row
    expired_qty = min(base_qty, float(base_amount))
    new_amount = max(0.0, float(base_amount) - expired_qty)
    money_lost = expired_qty * float(price_per_base or 0.0)
    c.execute("""
        UPDATE inventory
        SET base_amount=?, money_lost=COALESCE(money_lost,0)+?, expired_count=COALESCE(expired_count,0)+1
        WHERE id=?
    """, (new_amount, money_lost, item_id))
    conn.commit(); conn.close()
    return True, f"Expired {qty_ui} {ui_unit}. Lost ₪{money_lost:.2f}"

def expire_all(item_id: int) -> Tuple[bool, str]:
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT base_amount, price_per_base, name FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close(); return False, "Item not found"
    base_amount, price_per_base, name = row
    loss = float(base_amount) * float(price_per_base or 0.0)
    c.execute("""
        UPDATE inventory
        SET base_amount=0, money_lost=COALESCE(money_lost,0)+?, expired_count=COALESCE(expired_count,0)+1
        WHERE id=?
    """, (loss, item_id))
    conn.commit(); conn.close()
    return True, f"Expired all of {name}. Lost ₪{loss:.2f}"

def freeze_item(item_id: int) -> Tuple[bool, str]:
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT storage_state FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close(); return False, "Item not found"
    state = row[0]
    if state == "frozen":
        conn.close(); return False, "Already frozen"
    c.execute("UPDATE inventory SET storage_state='frozen', frozen_at=? WHERE id=?", (iso_today(), item_id))
    conn.commit(); conn.close()
    return True, "Frozen"

def thaw_item(item_id: int) -> Tuple[bool, str]:
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT storage_state, frozen_at, COALESCE(frozen_days_accum,0) FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close(); return False, "Item not found"
    state, frozen_at, accum = row
    if state != "frozen":
        conn.close(); return False, "Not frozen"
    extra_days = 0
    if frozen_at:
        try:
            extra_days = (today() - parse_iso(frozen_at)).days
        except Exception:
            extra_days = 0
    c.execute("""
        UPDATE inventory
        SET storage_state='fresh', thawed_at=?, frozen_days_accum=?, frozen_at=NULL
        WHERE id=?
    """, (iso_today(), int(accum) + max(0, extra_days), item_id))
    conn.commit(); conn.close()
    return True, "Thawed"

# -------------------------
# Recipes and batches
# -------------------------

def _ensure_recipe(prepared_item_id: int) -> int:
    conn = get_connection(); c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO recipes(prepared_item_id) VALUES (?)", (prepared_item_id,))
    conn.commit()
    c.execute("SELECT id FROM recipes WHERE prepared_item_id=?", (prepared_item_id,))
    rid = c.fetchone()[0]
    conn.close()
    return rid

def recipe_editor(prepared_item_id: int, user_id: int):
    rid = _ensure_recipe(prepared_item_id)
    conn = get_connection(); c = conn.cursor()

    st.caption("Build the recipe by adding ingredients and quantities in base units.")

    c.execute("""
      SELECT id, name, base_unit, price_per_base
      FROM inventory
      WHERE user_id=? AND kind='ingredient'
      ORDER BY name
    """, (user_id,))
    ing_rows = c.fetchall()

    if not ing_rows:
        st.info("No ingredients in inventory yet.")
        conn.close()
        return

    def _fmt(row):
        _id, _name, _base_unit, _ppb = row
        return f"{_name} [{_base_unit}]  (₪/base {(_ppb or 0):.2f})"

    col1, col2, col3 = st.columns([2, 1, 1])
    selected = col1.selectbox("Ingredient", options=ing_rows, format_func=_fmt, key=f"ri_sel_{prepared_item_id}")
    qty = col2.number_input("Qty base", min_value=0.0, step=1.0, value=0.0, key=f"ri_qty_{prepared_item_id}")
    if col3.button("Add or update", key=f"ri_add_{prepared_item_id}"):
        c.execute("""
          INSERT INTO recipe_components(recipe_id, ingredient_item_id, quantity_base)
          VALUES (?,?,?)
          ON CONFLICT(recipe_id, ingredient_item_id) DO UPDATE SET quantity_base=excluded.quantity_base
        """, (rid, selected[0], float(qty)))
        conn.commit()
        st.success("Component saved")
        st.experimental_rerun()

    c.execute("""
      SELECT rc.id, i.name, i.base_unit, rc.quantity_base, i.price_per_base
      FROM recipe_components rc
      JOIN inventory i ON i.id = rc.ingredient_item_id
      WHERE rc.recipe_id=?
      ORDER BY i.name
    """, (rid,))
    comps = c.fetchall()

    total_cost = 0.0
    if comps:
        for cid, nm, bu, q, ppb in comps:
            line_cost = float(q) * float(ppb or 0.0)
            total_cost += line_cost
            d1, d2, d3, d4 = st.columns([2, 1, 1, 1])
            d1.write(nm)
            d2.write(f"{q:.2f} {bu}")
            d3.write(f"₪{(ppb or 0.0):.2f}/base")
            if d4.button("Remove", key=f"ri_del_{cid}"):
                c.execute("DELETE FROM recipe_components WHERE id=?", (cid,))
                conn.commit()
                st.warning("Removed")
                st.experimental_rerun()

        st.metric("Estimated total ingredient cost", f"₪{total_cost:.2f}")

        colu1, colu2 = st.columns([1, 2])
        new_yield = colu1.number_input("Expected yield base", min_value=0.0, step=1.0, value=0.0, key=f"ri_yield_{prepared_item_id}")
        if colu2.button("Update item cost from recipe", key=f"ri_push_{prepared_item_id}"):
            c.execute("SELECT base_amount FROM inventory WHERE id=?", (prepared_item_id,))
            cur_base = float(c.fetchone()[0] or 0.0)
            yield_base = float(new_yield or cur_base)
            price_per_base = (total_cost / yield_base) if yield_base > 0 else 0.0
            c.execute("UPDATE inventory SET total_cost=?, price_per_base=? WHERE id=?", (total_cost, price_per_base, prepared_item_id))
            conn.commit()
            st.success(f"Item updated. Price per base now ₪{price_per_base:.2f}")
            st.experimental_rerun()
    else:
        st.info("No components yet.")

    conn.close()

def create_batch(prepared_item_id: int):
    with st.expander("Create batch for this prepared item"):
        col1, col2, col3 = st.columns(3)
        cooked = col1.date_input("Cooked at", value=today(), key=f"b_dt_{prepared_item_id}")
        total_yield_base = col2.number_input("Total yield base", min_value=0.0, step=1.0, value=0.0, key=f"b_ty_{prepared_item_id}")
        portion_size_base = col3.number_input("Portion size base", min_value=0.0, step=1.0, value=0.0, key=f"b_ps_{prepared_item_id}")
        e1, e2 = st.columns(2)
        batch_exp = e1.date_input("Batch expiration", value=today(), key=f"b_ex_{prepared_item_id}")
        batch_cost = e2.number_input("Batch cost override ₪", min_value=0.0, step=0.1, value=0.0, key=f"b_cost_{prepared_item_id}")
        if st.button("Create batch", key=f"b_create_{prepared_item_id}"):
            conn = get_connection()
            safely_execute(conn, """
              INSERT INTO batches(prepared_item_id, cooked_at, total_yield_base, portion_size_base, remaining_base, expiration, storage_state, batch_cost)
              VALUES (?, ?, ?, ?, ?, ?, 'fresh', ?)
            """, (prepared_item_id, cooked.strftime("%Y-%m-%d"), float(total_yield_base), float(portion_size_base), float(total_yield_base), batch_exp.strftime("%Y-%m-%d"), float(batch_cost)))
            conn.close()
            st.success("Batch created")
            st.experimental_rerun()

def list_batches(prepared_item_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, cooked_at, total_yield_base, portion_size_base, remaining_base, expiration, storage_state
      FROM batches
      WHERE prepared_item_id=?
      ORDER BY date(cooked_at) DESC
    """, (prepared_item_id,))
    rows = c.fetchall()
    conn.close()
    if not rows:
        st.caption("No batches yet.")
        return
    for bid, cooked, total_y, portion, remaining, exp, state in rows:
        col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 1.5, 2])
        col1.write(f"Cooked {cooked}")
        col2.write(f"Remaining {remaining:.1f} base")
        col3.write(f"Portion {portion:.1f} base")
        col4.write(state)
        if col5.button("Use one portion", key=f"b_use_{bid}"):
            use_batch_portion(bid)
            st.success("Portion used")
            st.experimental_rerun()

def use_batch_portion(batch_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT remaining_base, portion_size_base FROM batches WHERE id=?", (batch_id,))
    r = c.fetchone()
    if not r:
        conn.close(); return
    remaining, portion = r
    new_remaining = max(0.0, float(remaining) - float(portion or 0.0))
    c.execute("UPDATE batches SET remaining_base=? WHERE id=?", (new_remaining, batch_id))
    conn.commit(); conn.close()

# -------------------------
# Export
# -------------------------

def export_csv(rows: List[tuple]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "id","name","expiration","type","amount_ui","unit_ui","used_count","last_used_month","stable",
        "price_per_unit_legacy","expired_count","money_lost","kind","base_unit","base_amount",
        "total_cost","price_per_base","storage_state","frozen_at","thawed_at","frozen_days_accum",
        "thaw_shelf_life_days","recipe_note"
    ])
    for r in rows:
        writer.writerow(list(r))
    return out.getvalue().encode("utf-8")

# -------------------------
# UI
# -------------------------

def inventory():
    st.title("📦 Inventory")
    if "user_id" not in st.session_state:
        st.warning("Please login first")
        st.stop()
    user_id = st.session_state["user_id"]

    create_tables()
    run_migrations()

    # top controls
    with st.container():
        l1, l2, l3, l4, l5 = st.columns([2, 1.2, 1.2, 1, 1])
        query = l1.text_input("Search by name or type", placeholder="milk, rice, pizza")
        kind_filter = l2.selectbox("Kind filter", ["all", "ingredient", "prepared"])
        state_filter = l3.selectbox("State filter", ["all", "fresh", "frozen", "expired soon"])
        sort_by = l4.selectbox("Sort by", ["expiration", "name", "price per base"])
        direction = l5.selectbox("Order", ["asc", "desc"])

    st.caption("Ingredient and prepared items share the same list. Prices are normalized per base unit. Frozen items pause shelf life.")

    # add form
    with st.form("add_item_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([2, 1.2, 1.2, 1])
        name = c1.text_input("Name")
        kind = c2.selectbox("Kind", ["ingredient", "prepared"])
        typ = c3.selectbox("Type", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"])
        exp = c4.date_input("Expiration", value=today(), min_value=today())

        d1, d2, d3 = st.columns([1, 1, 1])
        amount_ui = d1.number_input("Amount", min_value=0.0, step=0.1, value=1.0)
        unit_ui = d2.selectbox("Unit", UNITS)
        total_cost = d3.number_input("Total cost ₪", min_value=0.0, step=0.1, value=0.0)

        stable = st.checkbox("Stable item keep visible at zero")
        recipe_note = None
        thaw_days = None

        if kind == "prepared":
            recipe_note = st.text_area("Recipe quick note optional", placeholder="Short ingredients list or link")
        thaw_days = st.number_input("Days safe after thaw optional", min_value=0, step=1, value=0)

        base_amount, base_unit = to_base(amount_ui, unit_ui)
        ppb = compute_price_per_base(total_cost, base_amount)
        hint_val, hint_lbl = format_price_hint(unit_ui, ppb)
        st.info(f"Stored as {base_amount:.2f} {base_unit}. Price hint {hint_val} {hint_lbl}")

        submitted = st.form_submit_button("Add item")
        if submitted:
            if not name.strip():
                st.error("Name is required")
            else:
                add_item(
                    user_id=user_id,
                    name=name.strip(),
                    expiration=exp.strftime("%Y-%m-%d"),
                    food_type=typ,
                    ui_amount=float(amount_ui),
                    ui_unit=unit_ui,
                    total_cost=float(total_cost),
                    kind=kind,
                    stable=stable,
                    recipe_note=recipe_note,
                    thaw_shelf_life_days=int(thaw_days) if thaw_days else None
                )
                st.success("Added")
                st.rerun()

    # list items
    rows = get_user_items(user_id)

    # filters
    filtered = []
    for r in rows:
        (
            item_id, name, exp, typ, amount_ui, unit_ui, used_count, last_m, stable, ppu_legacy,
            expired_steps, money_lost, kind, base_unit, base_amount, total_cost, price_per_base,
            storage_state, frozen_at, thawed_at, frozen_days_accum, thaw_days, recipe_note
        ) = r

        if query:
            q = query.lower()
            if q not in (name or "").lower() and q not in (typ or "").lower():
                continue
        if kind_filter != "all" and kind != kind_filter:
            continue

        eff_exp = effective_expiration(exp, storage_state, frozen_at, thawed_at, int(frozen_days_accum or 0))
        if state_filter == "frozen" and storage_state != "frozen":
            continue
        if state_filter == "expired soon":
            if (eff_exp - today()).days > 2:
                continue
        filtered.append((r, eff_exp))

    # sorting
    reverse = direction == "desc"
    if sort_by == "name":
        filtered.sort(key=lambda x: (x[0][1] or "").lower(), reverse=reverse)
    elif sort_by == "price per base":
        filtered.sort(key=lambda x: float(x[0][16] or 0.0), reverse=reverse)
    else:
        filtered.sort(key=lambda x: x[1], reverse=reverse)

    # export button
    exp_bytes = export_csv([f[0] for f in filtered] if filtered else rows)
    st.download_button("Export CSV", data=exp_bytes, file_name="inventory_export.csv", mime="text/csv")

    if not filtered:
        st.info("No items yet. Add something")
        return

    colA, colB = st.columns(2)
    for i, (r, eff_exp) in enumerate(filtered):
        (
            item_id, name, exp, typ, amount_ui, unit_ui, used_count, last_m, stable, ppu_legacy,
            expired_steps, money_lost, kind, base_unit, base_amount, total_cost, price_per_base,
            storage_state, frozen_at, thawed_at, frozen_days_accum, thaw_days, recipe_note
        ) = r

        status_text, color = status_badge(eff_exp, storage_state)
        hint_val, hint_lbl = format_price_hint(unit_ui if unit_ui in UNITS else base_unit, float(price_per_base or 0.0))

        host = colA if i % 2 == 0 else colB
        with host:
            st.markdown(f"""
                <div style='background:#1f1f1f;border-left:6px solid {color};
                            padding:14px 16px;border-radius:12px;margin-bottom:12px'>
                  <h4 style='margin:0;color:#fafafa'>{name} <span style='font-size:12px;color:#8ab4f8'>({kind})</span> <span style='font-size:12px;color:#888;'>[{typ}]</span></h4>
                  <p style='margin:4px 0;color:#ccc;'>📅 <b>Expires:</b> {eff_exp.strftime("%Y-%m-%d")}  |  🔔 <b>{status_text}</b></p>
                  <p style='margin:4px 0;color:#ccc;'>🔢 <b>On hand:</b> {base_amount:.2f} {base_unit}  |  💲 <b>Hint:</b> ₪{hint_val} {hint_lbl}</p>
                  <p style='margin:4px 0;color:#ccc;'>✅ Used entries: {used_count}  |  🗑️ Expired entries: {expired_steps}  |  💸 Lost: ₪{round(money_lost or 0.0, 2)}</p>
                  {"<p style='margin:4px 0;color:#0ff;'>Stable item</p>" if stable else ""}
                  {"<p style='margin:4px 0;color:#a0ffa0;'>Frozen</p>" if storage_state=='frozen' else ""}
                  {f"<p style='margin:4px 0;color:#ccc;'>Recipe note: {recipe_note}</p>" if recipe_note else ""}
                </div>
            """, unsafe_allow_html=True)

            a1, a2, a3, a4, a5 = st.columns([1.2, 1.4, 1.2, 1.2, 1.2])

            # quantity input in base units by default
            step = 0.1 if base_unit in ["g", "ml"] else 1.0
            qty = a2.number_input("Qty base", min_value=0.0, step=step, value=0.0, key=f"qty_{item_id}")

            if a1.button("Use qty", key=f"use_{item_id}"):
                ok, msg = use_quantity(item_id, qty, base_unit)
                if ok:
                    st.success(msg); st.rerun()
                else:
                    st.error(msg)

            if a3.button("Expire qty", key=f"exp_{item_id}"):
                ok, msg = expire_quantity(item_id, qty, base_unit)
                if ok:
                    st.warning(msg); st.rerun()
                else:
                    st.error(msg)

            if a4.button("Expire all", key=f"expall_{item_id}"):
                ok, msg = expire_all(item_id)
                if ok:
                    st.error(msg); st.rerun()
                else:
                    st.error(msg)

            if storage_state != "frozen":
                if a5.button("Freeze", key=f"freeze_{item_id}"):
                    ok, msg = freeze_item(item_id)
                    if ok:
                        st.info(msg); st.rerun()
                    else:
                        st.error(msg)
            else:
                if a5.button("Thaw", key=f"thaw_{item_id}"):
                    ok, msg = thaw_item(item_id)
                    if ok:
                        st.info(msg); st.rerun()
                    else:
                        st.error(msg)

            # prepared item tools
            if kind == "prepared":
                with st.expander("Recipe"):
                    recipe_editor(item_id, user_id)
                with st.expander("Batches"):
                    create_batch(item_id)
                    list_batches(item_id)

            with st.expander("Edit"):
                new_name = st.text_input("Name", value=name, key=f"nm_{item_id}")
                new_exp = st.date_input("Expiration", value=parse_iso(exp), key=f"ex_{item_id}")
                new_typ = st.text_input("Type", value=typ, key=f"tp_{item_id}")

                # show friendly fields, still store normalized
                # allow user to switch displayed unit
                ui_unit_choice = st.selectbox("Display unit", UNITS, index=UNITS.index(unit_ui) if unit_ui in UNITS else 0, key=f"uiunit_{item_id}")
                display_amount = from_base(base_amount, ui_unit_choice)
                new_amount_ui = st.number_input("Amount", min_value=0.0, value=float(display_amount), step=0.1, key=f"am_{item_id}")
                new_total = st.number_input("Total cost ₪", min_value=0.0, value=float(total_cost or 0.0), step=0.1, key=f"tt_{item_id}")
                new_kind = st.selectbox("Kind", ["ingredient", "prepared"], index=["ingredient", "prepared"].index(kind) if kind in ["ingredient", "prepared"] else 0, key=f"kd_{item_id}")
                new_thaw_days = st.number_input("Days safe after thaw optional", min_value=0, step=1, value=int(thaw_days or 0), key=f"td_{item_id}")
                new_recipe = st.text_area("Recipe note", value=recipe_note or "", key=f"rc_{item_id}")

                if st.button("Save", key=f"save_{item_id}"):
                    try:
                        update_item(
                            item_id=item_id,
                            name=new_name.strip(),
                            expiration=new_exp.strftime("%Y-%m-%d"),
                            food_type=new_typ,
                            ui_amount=float(new_amount_ui),
                            ui_unit=ui_unit_choice,
                            total_cost=float(new_total),
                            kind=new_kind,
                            thaw_shelf_life_days=int(new_thaw_days) if new_thaw_days else None,
                            recipe_note=new_recipe.strip() if new_recipe else None
                        )
                        st.success("Saved"); st.rerun()
                    except Exception as e:
                        st.error(str(e))

            if storage_state != "frozen" and thaw_days:
                st.caption(f"After thaw consume within about {thaw_days} day(s)")
.