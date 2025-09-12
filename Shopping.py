# Shopping.py
# Streamlit UI only. All logic lives in shopping_core.py.

from __future__ import annotations

from datetime import date
from typing import Dict, Optional, List

import streamlit as st
from db import get_connection

import shopping_core as core

# Router compatibility: some loaders import 'Shopping', others 'shopping'.
import sys as _sys
_sys.modules.setdefault("Shopping", _sys.modules[__name__])
_sys.modules.setdefault("shopping", _sys.modules[__name__])


# -----------------------------
# Session helpers
# -----------------------------
def _ensure_cart():
    if "cart" not in st.session_state:
        st.session_state.cart = []  # list[dict]


def _add_to_cart(row: Dict):
    _ensure_cart()
    st.session_state.cart.append(row)


def _remove_from_cart(idx: int):
    _ensure_cart()
    if 0 <= idx < len(st.session_state.cart):
        del st.session_state.cart[idx]


def _clear_cart():
    st.session_state.cart = []


# -----------------------------
# UI
# -----------------------------
def shopping():
    st.title("🛒 Shopping")

    if "user_id" not in st.session_state:
        st.warning("Please login first")
        st.stop()
    user_id = int(st.session_state["user_id"])

    # bootstrap DB shapes and clean names
    core.run_shopping_migrations()
    core.migrate_legacy_staple_names(user_id)

    _ensure_cart()

    # ---------------- Budget & spend ----------------
    with st.container():
        c1, c2, c3 = st.columns([1, 1, 2])
        monthly_budget = c1.number_input(
            "Monthly budget (₪)",
            min_value=0.0, step=50.0,
            value=float(st.session_state.get("budget", 0.0)),
            key="budget_input",
        )
        st.session_state["budget"] = float(monthly_budget)
        spent = core.month_spend(user_id)
        c2.metric("Spent this month", f"₪{spent:.2f}")
        if monthly_budget > 0:
            remaining = max(monthly_budget - spent, 0.0)
            c3.write(f"**Remaining:** ₪{remaining:.2f} of ₪{monthly_budget:.2f}")

    # ---------------- One-time importer ----------------
    with st.expander("One-time setup: import Israeli chains + staple items", expanded=False):
        st.caption("Creates chains, maps categories, fixes legacy names, and seeds a staple price book.")
        if st.button("Import defaults (clean names)"):
            core.seed_israel_defaults(user_id)
            st.success("Imported/updated chains, staples and baseline prices.")
            st.rerun()

    # ---------------- Shop by store (browse & add) ----------------
    with st.expander("🛍️ Shop by store (browse & add)", expanded=True):
        stores_all = core.get_stores(user_id)
        if not stores_all:
            st.info("Add a store first in the section below.")
        else:
            store_sel = st.selectbox(
                "Choose a store",
                options=stores_all,
                format_func=lambda r: r[1],
                key="shop_store_select",
            )

            q = st.text_input("Search item name (optional)", key="shop_q").strip().lower()
            type_filter = st.multiselect("Filter by type (optional)", core.FOOD_TYPES, key="shop_types")

            rows = core.get_store_prices_for_store(user_id, store_sel[0])
            filtered = []
            for it_id, nm, typ, bu, pq, pu, pp, ppb, seen, plink in rows:
                if q and q not in (nm or "").lower():
                    continue
                if type_filter and typ not in set(type_filter):
                    continue
                filtered.append((it_id, nm, typ, bu, pq, pu, pp, ppb, seen, plink))

            if not filtered:
                st.caption("No priced items at this store with the current filters.")
            else:
                st.caption(f"{len(filtered)} priced items at **{store_sel[1]}**")
                picked = []
                for it_id, nm, typ, bu, pq, pu, pp, ppb, seen, plink in filtered:
                    cols = st.columns([3, 1.2, 1.2, 1.0, 1.4, 1.2, 0.9, 0.7])
                    cols[0].markdown(f"**{nm}** · [{typ}] · base={bu}")
                    cols[1].write(f"{pq:g} {pu} for ₪{pp:g}")
                    cols[2].write(f"₪{ppb:.2f} / {bu}")
                    cols[3].markdown(f"[Product]({plink})" if plink else "—")
                    packs = cols[4].number_input("packs", min_value=0, step=1, value=0,
                                                 key=f"shop_packs_{store_sel[0]}_{it_id}")
                    exp_line = cols[5].date_input(
                        "expiry",
                        value=date.fromisoformat(core.suggest_expiration_for(user_id, it_id, nm, typ)),
                        key=f"shop_exp_{store_sel[0]}_{it_id}",
                    )
                    add_now = cols[6].button("Add", key=f"shop_add_{store_sel[0]}_{it_id}")
                    pick_cb = cols[7].checkbox("", value=False, key=f"shop_pick_{store_sel[0]}_{it_id}")

                    if add_now and packs > 0:
                        base_per_pack, _ = core.to_base(pq, pu)
                        qty_base = base_per_pack * float(packs)
                        _add_to_cart({
                            "item_id": it_id, "name": nm, "type": typ, "base_unit": bu,
                            "qty_base": float(qty_base),
                            "store_id": store_sel[0], "store_name": store_sel[1],
                            "unit_price_base": float(ppb),
                            "expiration": exp_line.strftime("%Y-%m-%d"),
                        })
                        st.success("Added to cart")
                    if pick_cb and packs > 0:
                        picked.append((it_id, nm, typ, bu, pq, pu, ppb, packs, exp_line))

                if picked and st.button("Add selected → Cart", key="shop_add_selected"):
                    for it_id, nm, typ, bu, pq, pu, ppb, packs, exp_line in picked:
                        base_per_pack, _ = core.to_base(pq, pu)
                        qty_base = base_per_pack * float(packs)
                        _add_to_cart({
                            "item_id": it_id, "name": nm, "type": typ, "base_unit": bu,
                            "qty_base": float(qty_base),
                            "store_id": store_sel[0], "store_name": store_sel[1],
                            "unit_price_base": float(ppb),
                            "expiration": exp_line.strftime("%Y-%m-%d"),
                        })
                    st.success(f"Added {len(picked)} item(s) to cart")

            st.divider()
            # Add a brand-new item directly to this store
            with st.expander(f"Add a NEW item to {store_sel[1]}", expanded=False):
                new_name = st.text_input("Item name", key=f"shop_new_name_{store_sel[0]}")
                new_type = st.selectbox("Food type", core.FOOD_TYPES, key=f"shop_new_type_{store_sel[0]}")
                base_unit = st.selectbox("Base unit", ["pcs", "g", "ml"], index=0, key=f"shop_new_base_{store_sel[0]}")
                pack_qty  = st.number_input("Pack qty", min_value=0.0, step=0.1, value=1.0, key=f"shop_new_qty_{store_sel[0]}")
                pack_unit = st.selectbox("Pack unit", core.UNITS, key=f"shop_new_unit_{store_sel[0]}")
                pack_price = st.number_input("Pack price ₪", min_value=0.0, step=0.1, value=0.0, key=f"shop_new_price_{store_sel[0]}")
                product_link = st.text_input("Product link (optional)", placeholder="https://store/product", key=f"shop_new_link_{store_sel[0]}")
                exp_seed = core.suggest_expiration_for(user_id, -1, new_name or "item", new_type)
                exp_prefill = st.date_input("Expiry (auto)", value=date.fromisoformat(exp_seed), key=f"shop_new_exp_{store_sel[0]}")
                add_packs = st.number_input("Add packs now", min_value=0, step=1, value=0, key=f"shop_new_addpacks_{store_sel[0]}")

                colS, colA = st.columns(2)
                if colS.button("Save price to this store", key=f"shop_new_save_{store_sel[0]}"):
                    if not new_name.strip():
                        st.error("Name is required")
                    else:
                        item_id = core.create_item_and_price(
                            user_id, new_name.strip(), new_type, base_unit,
                            store_sel[0], pack_qty, pack_unit, pack_price, product_url=product_link or None
                        )
                        st.success("Item saved to price book for this store")
                if colA.button("Save + add packs → Cart", key=f"shop_new_add_{store_sel[0]}"):
                    if not new_name.strip():
                        st.error("Name is required")
                    else:
                        item_id = core.create_item_and_price(
                            user_id, new_name.strip(), new_type, base_unit,
                            store_sel[0], pack_qty, pack_unit, pack_price, product_url=product_link or None
                        )
                        if add_packs > 0:
                            base_per_pack, _ = core.to_base(pack_qty, pack_unit)
                            qty_base = base_per_pack * float(add_packs)
                            ppb = (pack_price / base_per_pack) if base_per_pack > 0 else 0.0
                            _add_to_cart({
                                "item_id": item_id, "name": new_name.strip(), "type": new_type,
                                "base_unit": core.BASE_FOR.get(base_unit, "pcs"),
                                "qty_base": float(qty_base),
                                "store_id": store_sel[0], "store_name": store_sel[1],
                                "unit_price_base": float(ppb),
                                "expiration": exp_prefill.strftime("%Y-%m-%d"),
                            })
                            st.success("Saved and added to cart")
                        else:
                            st.info("Saved. Set 'Add packs now' > 0 if you want it in the cart.")

    # ---------------- Stores management ----------------
    with st.expander("Stores & what they sell", expanded=False):
        col1, col2, col3, col4, col5 = st.columns([2, 1, 1, 2, 2])
        new_name  = col1.text_input("Store name", key="store_name_input")
        new_kind  = col2.selectbox("Kind", ["local", "chain", "greengrocer", "online"], key="store_kind_select")
        new_city  = col3.text_input("City / Area", placeholder="optional", key="store_city_input")
        new_link  = col4.text_input("Online link", placeholder="https://...", key="store_link_input")
        new_notes = col5.text_input("Notes", placeholder="delivery, hours, etc.", key="store_notes_input")
        if st.button("Add / Update store"):
            if new_name.strip():
                core.add_or_update_store(user_id, new_name, new_kind, new_city, new_link, new_notes)
                st.success("Store saved")
                st.rerun()
            else:
                st.error("Store name is required")

        stores = core.get_stores(user_id)
        if stores:
            st.caption("Mark what each store sells:")
            for sid, sname, skind, scity, slink, snotes in stores:
                cats = core.get_store_categories(user_id, sid)
                with st.container():
                    cols = st.columns([2, 1, 2, 2, 1])
                    cols[0].markdown(f"**{sname}**  · _{skind}_  · {scity or ''}")
                    if slink: cols[2].markdown(f"[Open site]({slink})")
                    else:     cols[2].write("—")
                    cols[3].write(snotes or "")
                    if cols[4].button("Delete", key=f"del_store_{sid}"):
                        core.delete_store(sid)
                        st.warning("Store removed")
                        st.rerun()
                sel = st.multiselect(f"Categories for {sname}", core.FOOD_TYPES, default=cats, key=f"cats_{sid}")
                if st.button(f"Save categories for {sname}", key=f"save_cats_{sid}"):
                    core.set_store_categories(user_id, sid, sel)
                    st.success("Saved")
        else:
            st.info("No stores yet — add one above or click the importer.")

    # ---------------- Price book editor ----------------
    with st.expander("Price book (₪/base) + add to cart", expanded=False):
        inv = core.get_inventory(user_id)
        stores_all = core.get_stores(user_id)
        if not stores_all or not inv:
            st.info("Add at least one store and one inventory item to begin.")
        else:
            cA, cB = st.columns([1.2, 2])
            item_sel = cB.selectbox(
                "Inventory item",
                options=inv,
                format_func=lambda r: f"{r[1]} [{r[4]} · {r[2]}]",
                key="pb_item_select",
            )
            allowed_stores = core.stores_selling_type(user_id, item_sel[2]) or stores_all
            store_sel = cA.selectbox(
                "Store",
                options=allowed_stores,
                format_func=lambda r: f"{r[1]} ({r[2]})",
                key="pb_store",
            )

            p1, p2, p3, p4, p5, p6 = st.columns([1, 1, 1, 1, 1.6, 1.2])
            pack_qty    = p1.number_input("Pack qty", min_value=0.0, step=0.1, value=1.0, key="pb_qty")
            pack_unit   = p2.selectbox("Unit", core.UNITS, key="pb_unit")
            pack_price  = p3.number_input("Pack price ₪", min_value=0.0, step=0.1, value=0.0, key="pb_price")
            packs_to_add= p4.number_input("Add packs", min_value=0, step=1, value=0, key="pb_add")
            product_link= p5.text_input("Product link (optional)", placeholder="https://store/product", key="pb_product_link")
            exp_opt     = p6.date_input("Expiry (opt.)", value=date.today(), key="pb_exp")

            if st.button("Save price", key="pb_save_price"):
                core.upsert_store_price(user_id, store_sel[0], item_sel[0], pack_qty, pack_unit, pack_price,
                                        product_url=product_link or None)
                st.success("Price saved")

            if packs_to_add > 0 and st.button("Add packs → Cart", key="pb_add_cart"):
                base_per_pack, _ = core.to_base(pack_qty, pack_unit)
                qty_base = base_per_pack * float(packs_to_add)
                ppb = (pack_price / base_per_pack) if base_per_pack > 0 else 0.0
                exp = exp_opt.strftime("%Y-%m-%d") if exp_opt else core.suggest_expiration_for(user_id, item_sel[0], item_sel[1], item_sel[2])
                _add_to_cart({
                    "item_id": item_sel[0], "name": item_sel[1], "type": item_sel[2],
                    "base_unit": item_sel[4], "qty_base": float(qty_base),
                    "store_id": store_sel[0], "store_name": store_sel[1],
                    "unit_price_base": float(ppb),
                    "expiration": exp,
                })
                st.success("Added to cart")

            st.divider()
            st.subheader(f"Prices at {store_sel[1]}")
            rows = core.get_store_prices_for_store(user_id, store_sel[0])
            if rows:
                for it_id, nm, typ, bu, pq, pu, pp, ppb, seen, plink in rows:
                    cols = st.columns([3, 1.2, 1.2, 1.0, 1.4, 1.2, 0.9])
                    cols[0].markdown(f"**{nm}** · [{typ}] · base={bu}")
                    cols[1].write(f"{pq:g} {pu} for ₪{pp:g}")
                    cols[2].write(f"₪{ppb:.2f} / {bu}")
                    cols[3].markdown(f"[Product]({plink})" if plink else "—")
                    add_packs = cols[4].number_input("packs", min_value=0, step=1, value=0, key=f"packs_{store_sel[0]}_{it_id}")
                    exp_line = cols[5].date_input(
                        "expiry",
                        value=date.fromisoformat(core.suggest_expiration_for(user_id, it_id, nm, typ)),
                        key=f"exp_{store_sel[0]}_{it_id}",
                    )
                    if cols[6].button("Add", key=f"addbtn_{store_sel[0]}_{it_id}"):
                        if add_packs > 0:
                            base_per_pack, _ = core.to_base(pq, pu)
                            qty_base = base_per_pack * float(add_packs)
                            _add_to_cart({
                                "item_id": it_id, "name": nm, "type": typ,
                                "base_unit": bu, "qty_base": float(qty_base),
                                "store_id": store_sel[0], "store_name": store_sel[1],
                                "unit_price_base": float(ppb),
                                "expiration": exp_line.strftime("%Y-%m-%d"),
                            })
                            st.success("Added to cart")
                        else:
                            st.error("Set packs > 0 to add.")
            else:
                st.caption("No prices yet at this store.")

    # ---------------- Cheapest store finder ----------------
    with st.expander("Cheapest store finder (per item)", expanded=False):
        inv = core.get_inventory(user_id)
        if not inv:
            st.info("Inventory is empty.")
        else:
            pick = st.selectbox("Pick an item", options=inv,
                                format_func=lambda r: f"{r[1]} [{r[4]} · {r[2]}]",
                                key="cheapest_item")
            offers = core.get_prices_for_item(user_id, pick[0])
            if not offers:
                st.info("No price data yet. Save a few store prices first.")
            else:
                min_ppb = min([o[7] for o in offers if float(o[7] or 0) > 0] or [0.0])
                for sid, sname, skind, link_url, pq, pu, pp, ppb, plink, seen in offers:
                    cols = st.columns([2.2, 1.6, 1.6, 1.0, 1.2, 1.2, 0.9])
                    site_link = f"[{sname} site]({link_url})" if link_url else ""
                    cols[0].markdown(f"**{sname}** · _{skind}_ | {site_link}")
                    cols[1].write(f"{pq:g} {pu} → ₪{pp:g}")
                    cols[2].write(f"₪{ppb:.2f} / {pick[4]}")
                    cols[3].markdown(f"[Product]({plink})" if plink else "—")
                    # Cheapest badge
                    if ppb <= 0 or min_ppb <= 0:
                        cols[4].write("")
                    elif abs(ppb - min_ppb) <= max(1e-3, 1e-3 * min_ppb):
                        cols[4].write("✅ cheapest")
                    else:
                        diff = ppb - min_ppb
                        pct = 100.0 * diff / min_ppb
                        cols[4].write(f"❌ +₪{diff:.2f} (+{pct:.0f}%)")
                    add_here = cols[5].number_input("packs", min_value=0, step=1, value=0, key=f"cheapest_packs_{sid}_{pick[0]}")
                    if cols[6].button("Add", key=f"cheapest_add_{sid}_{pick[0]}"):
                        if add_here > 0:
                            base_per_pack, _ = core.to_base(pq, pu)
                            qty_base = base_per_pack * float(add_here)
                            exp = core.suggest_expiration_for(user_id, pick[0], pick[1], pick[2])
                            _add_to_cart({
                                "item_id": pick[0], "name": pick[1], "type": pick[2],
                                "base_unit": pick[4], "qty_base": float(qty_base),
                                "store_id": sid, "store_name": sname,
                                "unit_price_base": float(ppb),
                                "expiration": exp,
                            })
                            st.success("Added to cart")
                        else:
                            st.error("Set packs > 0 to add.")

    # ---------------- Stock rules ----------------
    with st.expander("Stock rules (Always-buy & Par levels)", expanded=False):
        inv = core.get_inventory(user_id)
        if not inv:
            st.info("Inventory is empty.")
        else:
            for (iid, nm, typ, _kind, bu, onhand, _ppb, always_buy, par, _stable) in inv:
                cols = st.columns([2.2, 1.2, 1.2, 1])
                cols[0].write(f"**{nm}**  _[{typ} · {bu}]_ — on hand: {onhand:.1f} {bu}")
                ab = cols[1].checkbox("Always buy", value=bool(always_buy), key=f"ab_{iid}")
                new_par = cols[2].number_input("Par (base)", min_value=0.0, step=core.step_size_for(bu),
                                               value=float(par or 0.0), key=f"par_{iid}")
                if cols[3].button("Save", key=f"sv_{iid}"):
                    core.set_item_rules(iid, ab, new_par)
                    st.success("Rules saved")

    # ---------------- Quick restock suggestions (auto) ----------------
    st.subheader("✨ Quick restock suggestions")
    stores_all = core.get_stores(user_id)
    colA, colB = st.columns([1, 3])
    force_store_on = colA.checkbox("Force adds to store", value=bool(st.session_state.get("force_store_id")))
    if force_store_on and stores_all:
        default_idx = 0
        if st.session_state.get("force_store_id"):
            try:
                default_idx = next(i for i, s in enumerate(stores_all) if s[0] == st.session_state["force_store_id"])
            except StopIteration:
                default_idx = 0
        chosen_store = colB.selectbox(
            "Choose store for all 'Add to cart' below",
            options=stores_all, index=default_idx,
            format_func=lambda r: r[1], key="force_store_sel",
        )
        st.session_state["force_store_id"] = chosen_store[0]
    else:
        st.session_state["force_store_id"] = None

    c1, c2 = st.columns([1, 1])
    target_days = c1.number_input("Target coverage (days)", min_value=3, max_value=60, value=14, step=1)
    threshold   = c2.number_input("Suggest when stock < days", min_value=1, max_value=30, value=7, step=1)

    suggestions = core.suggest_shopping_lines(user_id, target_days, threshold)
    if not suggestions:
        st.caption("No suggestions right now.")
    else:
        for idx, row in enumerate(suggestions):
            c1, c2, c3, c4, c5, c6 = st.columns([2, 1, 1.6, 1.2, 1.2, 1])
            c1.write(f"**{row['name']}** [{row['type']} · {row['base_unit']}]")
            qty = c2.number_input("Qty (base)", min_value=0.0, step=core.step_size_for(row["base_unit"]),
                                  value=float(row["qty_base"]), key=f"sugg_qty_{idx}")

            stores_ok = core.stores_selling_type(user_id, row["type"]) or stores_all
            best = core.best_price_for_item(user_id, row["item_id"])
            default_idx = 0
            store_opts = [(None, "—", "", "", "")]
            for i, s in enumerate(stores_ok):
                store_opts.append(s)
                if best and s[0] == best[0]:
                    default_idx = i + 1

            if st.session_state.get("force_store_id"):
                forced_id = st.session_state["force_store_id"]
                try:
                    forced_name = next(s[1] for s in stores_all if s[0] == forced_id)
                except StopIteration:
                    forced_name = "Store"
                c3.write(f"Store: **{forced_name}**")
                chosen = (forced_id, forced_name, "", "", "")
                unit_price_default = core.ppb_for_item_at_store(user_id, row["item_id"], forced_id) or float(row["unit_price_base"] or 0.0)
            else:
                chosen = c3.selectbox("Store", options=store_opts, index=default_idx,
                                      format_func=lambda r: r[1] if isinstance(r, tuple) else "—",
                                      key=f"sugg_store_{idx}")
                unit_price_default = float(row["unit_price_base"] or 0.0)

            unit_price = c4.number_input("₪/base", min_value=0.0, step=0.1,
                                         value=unit_price_default, key=f"sugg_ppb_{idx}")
            exp_default = row.get("expiration") or core.suggest_expiration_for(user_id, row["item_id"], row["name"], row["type"])
            exp = c5.date_input("Expiry (opt.)", value=date.fromisoformat(exp_default), key=f"sugg_exp_{idx}")

            if c6.button("Add to cart", key=f"sugg_add_{idx}"):
                use_store_id = None
                use_store_name = None
                if st.session_state.get("force_store_id"):
                    use_store_id = st.session_state["force_store_id"]
                    try:
                        use_store_name = next(s[1] for s in stores_all if s[0] == use_store_id)
                    except StopIteration:
                        use_store_name = None
                    ppb_forced = core.ppb_for_item_at_store(user_id, row["item_id"], use_store_id)
                    if ppb_forced > 0:
                        unit_price = ppb_forced
                else:
                    if chosen[0] is not None:
                        use_store_id = chosen[0]
                        use_store_name = chosen[1]

                _add_to_cart({
                    "item_id": row["item_id"], "name": row["name"], "type": row["type"],
                    "base_unit": row["base_unit"],
                    "qty_base": float(qty),
                    "store_id": use_store_id, "store_name": use_store_name,
                    "unit_price_base": float(unit_price),
                    "expiration": exp.strftime("%Y-%m-%d"),
                })
                st.success("Added to cart")

    # ---------------- Cart ----------------
    st.subheader("🧺 Cart")
    if not st.session_state.cart:
        st.info("Cart is empty.")
    else:
        totals_by_store: Dict[Optional[int], float] = {}
        grand = 0.0
        for idx, row in enumerate(st.session_state.cart):
            unit_total = float(row.get("unit_price_base") or 0.0) * float(row["qty_base"])
            store_key = row.get("store_id")
            totals_by_store[store_key] = totals_by_store.get(store_key, 0.0) + unit_total
            grand += unit_total

            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns([2.2, 1, 1.2, 1.6, 1.6, 1.2, 1.2, 0.8])
            c1.write(f"**{row['name']}** [{row.get('base_unit','')}]")
            row["qty_base"] = c2.number_input("Qty (base)", min_value=0.0,
                                              step=core.step_size_for(row.get("base_unit","pcs")),
                                              value=float(row["qty_base"]), key=f"cart_qty_{idx}")
            row["unit_price_base"] = c3.number_input("₪/base", min_value=0.0, step=0.1,
                                                     value=float(row.get("unit_price_base") or 0.0),
                                                     key=f"cart_ppb_{idx}")
            stores = core.get_stores(user_id)
            store_opts = [(None, "—", "", "", "")] + stores
            cur_index = 0 if row.get("store_id") is None else 1 + next((i for i, s in enumerate(stores) if s[0] == row["store_id"]), 0)
            chosen = c4.selectbox("Store", options=store_opts, index=cur_index,
                                  format_func=lambda r: r[1] if isinstance(r, tuple) else "—",
                                  key=f"cart_store_{idx}")
            row["store_id"] = None if chosen[0] is None else chosen[0]
            row["store_name"] = None if chosen[0] is None else chosen[1]
            exp_str = row.get("expiration") or core.suggest_expiration_for(user_id, row["item_id"], row.get("name",""), row.get("type","Other"))
            row["expiration"] = c5.date_input("Expiry", value=date.fromisoformat(exp_str),
                                              key=f"cart_exp_{idx}").strftime("%Y-%m-%d")
            c6.write(f"Line: ₪{row['unit_price_base'] * row['qty_base']:.2f}")
            c7.write(f"Store: {row.get('store_name') or '—'}")
            if c8.button("✕", key=f"rm_{idx}"):
                _remove_from_cart(idx)
                st.rerun()

        st.divider()
        for sid, total in totals_by_store.items():
            store_name = "No store" if sid is None else next((s[1] for s in core.get_stores(user_id) if s[0] == sid), "Store")
            st.write(f"**{store_name}** — ₪{total:.2f}")
        st.write(f"**Grand total: ₪{grand:.2f}**")

        budget = float(st.session_state.get("budget", 0.0))
        already = core.month_spend(user_id)
        if budget > 0 and already + grand > budget:
            st.warning(f"Budget alert: this checkout would bring you to ₪{already + grand:.2f} > ₪{budget:.2f}")

        colx, coly, _ = st.columns([1, 1, 2])
        if colx.button("Clear cart"):
            _clear_cart()
            st.rerun()
        if coly.button("Checkout"):
            # Convert to core.CartLine list
            cart_lines: List[core.CartLine] = []
            for r in st.session_state.cart:
                cart_lines.append(core.CartLine(
                    item_id=int(r["item_id"]),
                    qty_base=float(r["qty_base"]),
                    unit_price_base=float(r.get("unit_price_base") or 0.0),
                    store_id=r.get("store_id"),
                    expiration=r.get("expiration"),
                ))
            ok, msg = core.checkout_cart(user_id, cart_lines)
            if ok:
                st.success(msg)
                _clear_cart()
                st.rerun()
            else:
                st.error(msg)

    # ---------------- Templates ----------------
    with st.expander("Save / Load lists", expanded=False):
        title = st.text_input("List title", key="tmpl_title_input")
        if st.button("Save current cart as template", key="tmpl_save_btn"):
            if not st.session_state.cart:
                st.error("Cart is empty")
            elif not title.strip():
                st.error("Title is required")
            else:
                conn = get_connection(); c = conn.cursor()
                c.execute(
                    "INSERT INTO shopping_lists(user_id, title, status, created_at) VALUES (?,?, 'template', ?)",
                    (user_id, title.strip(), core.iso_today()),
                )
                list_id = c.lastrowid
                for row in st.session_state.cart:
                    c.execute("""
                      INSERT INTO shopping_list_items(list_id, item_id, desired_qty_base, chosen_store_id,
                                                     est_unit_price_base, est_total, expiration)
                      VALUES (?,?,?,?,?,?,?)
                    """, (
                        list_id, row["item_id"], row["qty_base"], row.get("store_id"),
                        row.get("unit_price_base"),
                        (row.get("unit_price_base") or 0.0) * row["qty_base"],
                        row.get("expiration"),
                    ))
                conn.commit(); conn.close()
                st.success("Saved as template")

        conn = get_connection(); c = get_connection().cursor()
        c.execute("""
          SELECT id, title, created_at FROM shopping_lists
          WHERE user_id=? AND status='template' ORDER BY created_at DESC
        """, (user_id,))
        templates = c.fetchall(); c.connection.close()
        if templates:
            chosen = st.selectbox("Load template", options=templates,
                                  format_func=lambda r: f"{r[1]} ({r[2]})", key="tmpl_load_select")
            if st.button("Load → cart", key="tmpl_load_btn"):
                conn = get_connection(); c = conn.cursor()
                c.execute("""
                  SELECT item_id, desired_qty_base, chosen_store_id, est_unit_price_base, expiration
                  FROM shopping_list_items WHERE list_id=?
                """, (chosen[0],))
                rows = c.fetchall(); conn.close()
                _clear_cart()
                inv_all = core.get_inventory(user_id)
                for item_id, qty, store_id, unit_ppb, exp in rows:
                    meta = next((r for r in inv_all if r[0] == item_id), None)
                    if not meta:
                        continue
                    _add_to_cart({
                        "item_id": item_id, "name": meta[1], "type": meta[2], "base_unit": meta[4],
                        "qty_base": float(qty or 0.0),
                        "store_id": store_id, "store_name": None,
                        "unit_price_base": float(unit_ppb or 0.0),
                        "expiration": exp or core.suggest_expiration_for(user_id, item_id, meta[1], meta[2]),
                    })
                st.success("Template loaded to cart")


# Entry points for the router
def app():
    shopping()

# also expose a direct symbol some routers expect
app = shopping

if __name__ == "__main__":
    shopping()
