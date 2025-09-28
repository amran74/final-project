# Inventory.py — Streamlit UI thin layer over inventory_core (with Guide tab)
from __future__ import annotations

from datetime import date
from typing import List, Tuple

import streamlit as st
import inventory_core as core

st.set_page_config(page_title="Inventory", page_icon="📦", layout="wide")


# --------------------------- GUIDE CONTENT ------------------------------------
def _inventory_guide():
    st.title("📘 Inventory Guide")

    st.markdown("""
### What this page is
Track everything you have: ingredients and prepared foods. Log amounts, cost, and expiration, then **use / expire / freeze / thaw** with a click.  
Price-per-base is always computed so recipes, shopping, and waste analytics stay consistent.

---

### Quick start
1. **Add an item** at the top (name, kind, type, amount+unit, cost, expiration).  
2. Toggle **Stable item** if you want it to stay visible even at 0 (e.g., salt, oil).  
3. Use **Use qty** or **Expire qty** on a card as you cook or toss.  
4. Click **Freeze/Thaw** to track frozen state and safe‐after‐thaw days.

---

### Search & filters
- **Search**: matches name or type.  
- **Kind filter**: show `ingredient`, `prepared`, or `all`.  
- **State filter**: `fresh`, `frozen`, or `expired soon` (<= 2 days).  
- **Sort**: by expiration, name, or price per base; choose ascending/descending.

---

### Units & price math
- You enter **Amount + Unit** (pcs, g/kg, ml/l).  
- The app converts to **base units** (pcs/g/ml) and stores an internal `price_per_base`.  
- The card shows a **hint**:
  - ₪ per **100 g** for solid weight units
  - ₪ per **100 ml** for liquid units
  - ₪ per **piece** for countables
- **Tip:** Use the “Auto-parse quantity from name” checkbox to extract quantity from names like _“Tuna 500g”_ or _“Eggs 12 pack”_.

---

### Stable items
- “**Stable**” is for staples you always keep around.  
- When stable + **0 on hand**, the item is **not removed** and its expiry is ignored (shown as “Not stocked”).  
- Non-stable items at 0 are automatically cleaned up.

---

### Using / expiring amounts
Each card has quick actions:
- **Use qty** — deducts from on-hand and logs usage (affects “Used” stats).
- **Expire qty** — marks that quantity as expired (affects “Expired” and “Money lost” stats).
- **Expire all** — expire the entire remainder.

You’ll see usage/expiry counters and cumulative money lost right on the card.

---

### Freezing & thawing
- Click **Freeze** to move the item to the frozen state (expiry handled accordingly).  
- Click **Thaw** to bring it back; if you set **days safe after thaw**, you’ll get a post-thaw safety window.

---

### Prepared items (costed recipes)
Set **Kind = prepared** to manage things you cook in batches (soups, sauces, bakes):
1. Open **Recipe** expander on the item card.
2. Pick ingredients from your inventory, enter **Qty base**, and **Add or update**.
3. The app totals **ingredient cost** for you.
4. (Optional) enter an expected **yield** and click **Update item cost from recipe** to push the computed cost back into the item.

#### Batches
Track production runs:
- Set cooked date, **portion size**, **total yield**, batch **expiry**, and optional **cost override**; then **Create batch**.  
- The list shows remaining base amount and lets you **Use one portion** quickly.

---

### Editing items
- Use the **Edit** expander: change name, expiry, type, display unit, amount, total cost, kind, thaw days, and notes.  
- **Delete** requires a confirm checkbox to prevent accidents.

---

### Export
Click **Export CSV** to download your (filtered) inventory as a spreadsheet.

---

### FAQ & tips
- **Why is “Not stocked” shown?**  
  That’s a stable item at zero; we keep it for convenience.
- **My g/ml items nudge by big steps when using qty inputs.**  
  We default to **100 g / 100 ml** for speed; change the number field if you need a custom amount.
- **Price per base is missing?**  
  Add **Total cost** when creating/editing, or compute from prepared recipe cost.
- **Performance tip**: Filtering and sorting are done in-memory for snappy UI. Tighten search/filters when you have thousands of items.
    """)

    st.info("You can hide this guide any time — it won’t affect your data.")


# --------------------------- BROWSE/UI ----------------------------------------
def _browse_inventory(user_id: int):
    # Migrations + safety sweeps
    core.run_migrations()
    fixed_stable0 = core.normalize_stable_zero_expiry(user_id)
    removed_zeros = core.cleanup_depleted_items(user_id)
    removed_expired = core.cleanup_expired_items(user_id)
    if fixed_stable0 or removed_zeros or removed_expired:
        msg = []
        if fixed_stable0: msg.append(f"fixed {fixed_stable0} stable@0 expiry")
        if removed_zeros: msg.append(f"cleaned {removed_zeros} depleted")
        if removed_expired: msg.append(f"auto-removed {removed_expired} expired")
        st.info(", ".join(msg) + " item(s).")

    # Filters
    with st.container():
        l1, l2, l3, l4, l5 = st.columns([2, 1.2, 1.2, 1, 1])
        query = l1.text_input("Search by name or type", placeholder="milk, rice, pizza")
        kind_filter = l2.selectbox("Kind filter", ["all", "ingredient", "prepared"])
        state_filter = l3.selectbox("State filter", ["all", "fresh", "frozen", "expired soon"])
        sort_by = l4.selectbox("Sort by", ["expiration", "name", "price per base"])
        direction = l5.selectbox("Order", ["asc", "desc"])

    st.caption("Stable items at 0 show as ‘Not stocked’ (no expiry). Non-stable items at 0 are removed automatically.")

    # Add form
    with st.form("add_item_form", clear_on_submit=True):
        c1, c2, c3, c4 = st.columns([2, 1.2, 1.2, 1])
        name = c1.text_input("Name")
        kind = c2.selectbox("Kind", ["ingredient", "prepared"])
        typ = c3.selectbox("Type", core.CATEGORIES, index=core.CATEGORIES.index("Other"))
        exp = c4.date_input("Expiration", value=core.today(), min_value=core.today(), max_value=core.FAR_FUTURE)

        d1, d2, d3 = st.columns([1, 1, 1])
        amount_ui = d1.number_input("Amount", min_value=0.0, step=0.1, value=1.0)
        unit_ui = d2.selectbox("Unit", core.UNITS)
        total_cost = d3.number_input("Total cost ₪", min_value=0.0, step=0.1, value=0.0)

        stable = st.checkbox("Stable item keep visible at zero")
        recipe_note = st.text_area("Notes optional", placeholder="Anything to remember about this item or recipe")
        thaw_days = st.number_input("Days safe after thaw optional", min_value=0, step=1, value=0)
        auto_parse = st.checkbox("Auto-parse quantity from name (e.g., 'Eggs 12 pack', 'Tuna 500g')", value=True)

        # Hint default cap if user leaves it 0
        default_cap = core.default_thaw_days(typ)
        if (not thaw_days) and default_cap:
            st.caption(f"Default post-thaw cap for {typ}: {default_cap} day(s). Leave 0 to use it.")

        base_amount, base_unit = core.to_base(amount_ui, unit_ui)
        ppb = core.compute_price_per_base(total_cost, base_amount)

        def _fmt_price_hint(ui_unit: str, price_per_base: float):
            if ui_unit in ["kg", "g", "mg"]:   return f"{price_per_base * 100:.2f}", "per 100 g"
            if ui_unit in ["l", "ml"]:         return f"{price_per_base * 100:.2f}", "per 100 ml"
            return f"{price_per_base:.2f}", "per piece"

        hint_val, hint_lbl = _fmt_price_hint(unit_ui, ppb)
        st.info(f"Stored as {base_amount:.2f} {base_unit}. Price hint ₪{hint_val} {hint_lbl}")

        if core.is_stable_zero(stable, base_amount):
            st.caption("Stable + 0: expiry will be ignored (shown as Not stocked).")

        submitted = st.form_submit_button("Add item")
        if submitted:
            if not name.strip():
                st.error("Name is required")
            else:
                core.add_item(
                    user_id=user_id,
                    name=name.strip(),
                    expiration=exp.strftime("%Y-%m-%d"),
                    food_type=typ,
                    ui_amount=float(amount_ui),
                    ui_unit=unit_ui,
                    total_cost=float(total_cost),
                    kind=kind,
                    stable=stable,
                    recipe_note=recipe_note.strip() if recipe_note else None,
                    thaw_shelf_life_days=int(thaw_days) if thaw_days else None,
                    auto_parse=auto_parse
                )
                st.success("Added")
                st.rerun()

    # Fetch rows
    rows = core.get_user_items(user_id)

    # Filter in memory
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

        thaw_eff = (int(thaw_days) if thaw_days else core.default_thaw_days(typ))

        # pass thaw_eff so post-thaw life is respected
        eff_exp, status_text, color, no_expiry = core.effective_expiration_display(
            exp, storage_state, frozen_at, thawed_at, int(frozen_days_accum or 0), stable, base_amount, thaw_eff
        )
        if state_filter == "frozen" and storage_state != "frozen":
            continue
        if state_filter == "expired soon":
            if no_expiry or (eff_exp - core.today()).days > 2:
                continue
        filtered.append((r, eff_exp, status_text, color, no_expiry, thaw_eff))

    reverse = direction == "desc"
    if sort_by == "name":
        filtered.sort(key=lambda x: (x[0][1] or "").lower(), reverse=reverse)
    elif sort_by == "price per base":
        filtered.sort(key=lambda x: float(x[0][16] or 0.0), reverse=reverse)
    else:
        filtered.sort(key=lambda x: x[1], reverse=reverse)

    # Export
    exp_bytes = core.export_csv([f[0] for f in filtered] if filtered else rows)
    st.download_button("Export CSV", data=exp_bytes, file_name="inventory_export.csv", mime="text/csv")

    if not filtered:
        st.info("No items yet. Add something")
        return

    # Render cards
    colA, colB = st.columns(2)
    for i, (r, eff_exp, status_text, color, no_expiry, thaw_eff) in enumerate(filtered):
        (
            item_id, name, exp, typ, amount_ui, unit_ui, used_count, last_m, stable, ppu_legacy,
            expired_steps, money_lost, kind, base_unit, base_amount, total_cost, price_per_base,
            storage_state, frozen_at, thawed_at, frozen_days_accum, thaw_days, recipe_note
        ) = r

        price_pb_display = core.effective_price_per_base(price_per_base, ppu_legacy, unit_ui, base_unit)

        def _fmt_price_hint(ui_unit: str, price_per_base: float):
            if ui_unit in ["kg", "g", "mg"]:   return f"{price_per_base * 100:.2f}", "per 100 g"
            if ui_unit in ["l", "ml"]:         return f"{price_per_base * 100:.2f}", "per 100 ml"
            return f"{price_per_base:.2f}", "per piece"

        hint_val, hint_lbl = _fmt_price_hint(unit_ui if unit_ui in core.UNITS else base_unit, float(price_pb_display or 0.0))

        host = colA if i % 2 == 0 else colB
        with host:
            # Build effective expiry and a short explanation only if needed
            if no_expiry:
                exp_html = "—"
                explain_html = ""
            else:
                eff_b, base_b, paused_b, thaw_cap_b, remain_thaw = core.effective_expiration_explain(
                    exp, storage_state, frozen_at, thawed_at, int(frozen_days_accum or 0), thaw_eff
                )
                exp_html = eff_b.strftime("%Y-%m-%d")
                parts = []
                if paused_b > 0:
                    parts.append(f"base {base_b.strftime('%Y-%m-%d')} + {paused_b}d frozen pause")
                if thawed_at and remain_thaw is not None:
                    parts.append(f"resumes {remain_thaw}d after thaw ({thawed_at})")
                if thaw_cap_b and thaw_cap_b <= eff_b:
                    parts.append(f"capped by post-thaw to {thaw_cap_b.strftime('%Y-%m-%d')}")
                explain_html = f"<br><span style='color:#888;'>{' · '.join(parts)}</span>" if parts else ""

            st.markdown(f"""
                <div style='background:#1f1f1f;border-left:6px solid {color};
                            padding:14px 16px;border-radius:12px;margin-bottom:12px'>
                  <h4 style='margin:0;color:#fafafa'>{name} <span style='font-size:12px;color:#8ab4f8'>({kind})</span> <span style='font-size:12px;color:#888;'>[{typ}]</span></h4>
                  <p style='margin:4px 0;color:#ccc;'>📅 <b>Expires:</b> {exp_html}{explain_html}  |  🔔 <b>{status_text}</b></p>
                  <p style='margin:4px 0;color:#ccc;'>🔢 <b>On hand:</b> {base_amount:.2f} {base_unit}  |  💲 <b>Hint:</b> ₪{hint_val} {hint_lbl}</p>
                  <p style='margin:4px 0;color:#ccc;'>✅ Used entries: {used_count}  |  🗑️ Expired entries: {expired_steps}  |  💸 Lost: ₪{round(money_lost or 0.0, 2)}</p>
                  {"<p style='margin:4px 0;color:#0ff;'>Stable item</p>" if stable else ""}
                  {"<p style='margin:4px 0;color:#a0ffa0;'>Frozen</p>" if storage_state=='frozen' else ""}
                  {f"<p style='margin:4px 0;color:#ccc;'>Notes: {recipe_note}</p>" if recipe_note else ""}
                </div>
            """, unsafe_allow_html=True)

            a1, a2, a3, a4, a5 = st.columns([1.2, 1.4, 1.2, 1.2, 1.2])
            if base_unit == "g":
                step = 100.0; qty_label_unit = "g"
            elif base_unit == "ml":
                step = 100.0; qty_label_unit = "ml"
            else:
                step = 1.0; qty_label_unit = "pcs"

            qty = a2.number_input(f"Qty ({qty_label_unit if base_unit in ['g','ml'] else 'pcs'})",
                                  min_value=0.0, step=step, value=0.0, key=f"qty_{item_id}")

            if a1.button("Use qty", key=f"use_{item_id}"):
                ok, msg = core.use_quantity(item_id, qty, base_unit)
                st.success(msg) if ok else st.error(msg); st.rerun()

            if a3.button("Expire qty", key=f"exp_{item_id}"):
                ok, msg = core.expire_quantity(item_id, qty, base_unit)
                st.warning(msg) if ok else st.error(msg); st.rerun()

            if a4.button("Expire all", key=f"expall_{item_id}"):
                ok, msg = core.expire_all(item_id)
                st.error(msg) if ok else st.error(msg); st.rerun()

            if storage_state != "frozen":
                if a5.button("Freeze", key=f"freeze_{item_id}"):
                    ok, msg = core.freeze_item(item_id)
                    st.info(msg) if ok else st.error(msg); st.rerun()
            else:
                if a5.button("Thaw", key=f"thaw_{item_id}"):
                    ok, msg = core.thaw_item(item_id)
                    st.info(msg) if ok else st.error(msg); st.rerun()

            if kind == "prepared":
                with st.expander("Recipe"):
                    # ingredient picker
                    conn = core.get_connection()
                    cur = conn.cursor()
                    cur.execute("""
                      SELECT id, name, base_unit, price_per_base
                      FROM inventory
                      WHERE user_id=? AND kind='ingredient'
                      ORDER BY name
                    """, (user_id,))
                    ing_rows = cur.fetchall(); conn.close()

                    if not ing_rows:
                        st.info("No ingredients in inventory yet.")
                    else:
                        def _fmt(row): return f"{row[1]} [{row[2]}]  (₪/base {(row[3] or 0):.2f})"
                        col1, col2, col3 = st.columns([2, 1, 1])
                        selected = col1.selectbox("Ingredient", options=ing_rows, format_func=_fmt, key=f"ri_sel_{item_id}")
                        qtyb = col2.number_input("Qty base", min_value=0.0, step=1.0, value=0.0, key=f"ri_qty_{item_id}")
                        if col3.button("Add or update", key=f"ri_add_{item_id}"):
                            core.add_or_update_recipe_component(item_id, selected[0], float(qtyb))
                            st.success("Component saved"); st.rerun()

                        comps = core.recipe_components(user_id, item_id)
                        total_cost_calc = 0.0
                        for cid, nm, bu, q, ppb in comps:
                            line_cost = float(q) * float(ppb or 0.0); total_cost_calc += line_cost
                            d1, d2, d3, d4 = st.columns([2, 1, 1, 1])
                            d1.write(nm); d2.write(f"{q:.2f} {bu}"); d3.write(f"₪{(ppb or 0.0):.2f}/base")
                            if d4.button("Remove", key=f"ri_del_{cid}"):
                                core.delete_recipe_component(cid); st.warning("Removed"); st.rerun()
                        if comps:
                            st.metric("Estimated total ingredient cost", f"₪{total_cost_calc:.2f}")
                            colu1, colu2 = st.columns([1, 2])
                            new_yield = colu1.number_input("Expected yield base", min_value=0.0, step=1.0, value=0.0, key=f"ri_yield_{item_id}")
                            if colu2.button("Update item cost from recipe", key=f"ri_push_{item_id}"):
                                core.push_recipe_cost_to_item(item_id, total_cost_calc, float(new_yield or 0.0))
                                st.success("Item updated from recipe"); st.rerun()

            with st.expander("Edit"):
                new_name = st.text_input("Name", value=name, key=f"nm_{item_id}")
                new_exp = st.date_input("Base expiration (raw before freeze/thaw math)",
                                        value=min(core.parse_iso(exp), core.FAR_FUTURE),
                                        max_value=core.FAR_FUTURE, key=f"ex_{item_id}")

                new_typ = st.selectbox("Type", core.CATEGORIES,
                                       index=(core.CATEGORIES.index(typ) if typ in core.CATEGORIES else core.CATEGORIES.index("Other")),
                                       key=f"tp_{item_id}")

                ui_unit_choice = st.selectbox("Display unit", core.UNITS,
                                              index=core.UNITS.index(unit_ui) if unit_ui in core.UNITS else 0,
                                              key=f"uiunit_{item_id}")
                display_amount = core.from_base(base_amount, ui_unit_choice)
                new_amount_ui = st.number_input("Amount", min_value=0.0, value=float(display_amount), step=0.1, key=f"am_{item_id}")
                new_total = st.number_input("Total cost ₪", min_value=0.0, value=float(total_cost or 0.0), step=0.1, key=f"tt_{item_id}")
                new_kind = st.selectbox("Kind", ["ingredient", "prepared"], index=(0 if kind != "prepared" else 1), key=f"kd_{item_id}")
                new_thaw_days = st.number_input("Days safe after thaw optional", min_value=0, step=1, value=int(thaw_days or 0), key=f"td_{item_id}")
                new_recipe = st.text_area("Notes", value=recipe_note or "", key=f"rc_{item_id}")
                auto_parse_edit = st.checkbox("Auto-parse quantity from name", value=True, key=f"ap_{item_id}")

                # Echo effective date with explanation
                if not no_expiry:
                    eff_b, base_b, paused_b, thaw_cap_b, remain_thaw = core.effective_expiration_explain(
                        exp, storage_state, frozen_at, thawed_at,
                        int(frozen_days_accum or 0),
                        int(new_thaw_days) if new_thaw_days else core.default_thaw_days(new_typ or typ)
                    )
                    bits = []
                    if paused_b > 0:
                        bits.append(f"+{paused_b}d frozen pause")
                    if thawed_at and remain_thaw is not None:
                        bits.append(f"resumes {remain_thaw}d after thaw ({thawed_at})")
                    if thaw_cap_b:
                        bits.append(f"post-thaw cap {thaw_cap_b.strftime('%Y-%m-%d')}")
                    st.caption(f"Effective expiry: {eff_b.strftime('%Y-%m-%d')}" + (f" ({'; '.join(bits)})" if bits else ""))

                del_cols = st.columns([1, 1.6, 1])
                confirm_del = del_cols[0].checkbox("Confirm delete", key=f"delc_{item_id}")
                if del_cols[1].button("Delete item", key=f"del_{item_id}"):
                    if confirm_del:
                        core.delete_item(item_id); st.warning("Item deleted."); st.rerun()
                    else:
                        st.error("Please check 'Confirm delete' first.")

                if st.button("Save", key=f"save_{item_id}"):
                    try:
                        core.update_item(
                            item_id=item_id,
                            name=new_name.strip(),
                            expiration=new_exp.strftime("%Y-%m-%d"),
                            food_type=new_typ,
                            ui_amount=float(new_amount_ui),
                            ui_unit=ui_unit_choice,
                            total_cost=float(new_total),
                            kind=new_kind,
                            thaw_shelf_life_days=int(new_thaw_days) if new_thaw_days else None,
                            recipe_note=new_recipe.strip() if new_recipe else None,
                            stable_flag=bool(stable),
                            auto_parse=auto_parse_edit
                        )
                        st.success("Saved"); st.rerun()
                    except Exception as e:
                        st.error(str(e))

            if storage_state != "frozen" and thaw_eff:
                st.caption(f"After thaw consume within about {thaw_eff} day(s)")


# --------------------------- ENTRY POINTS -------------------------------------
def inventory():
    st.title("📦 Inventory")

    if "user_id" not in st.session_state:
        st.warning("Please login first")
        st.stop()
    user_id = int(st.session_state["user_id"])

    tabs = st.tabs(["Browse", "Guide"])
    with tabs[0]:
        _browse_inventory(user_id)
    with tabs[1]:
        _inventory_guide()


# entry points expected by your app router
def app():
    inventory()


if __name__ == "__main__":
    inventory()
