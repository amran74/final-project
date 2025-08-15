# Inventory.py — Smart Coach: Risk scoring, auto plan, freeze, optimizer
import streamlit as st
from datetime import datetime, date, timedelta
from typing import Tuple, List, Dict

from db import (
    get_connection,
    update_item as db_update_item,
    use_item, use_one_step,
    expire_item, expire_all,
    get_monthly_summary,
)

# ---------- DB helpers ----------
def add_item(user_id, name, expiration, food_type, amount, unit, stable=False, price_per_unit=0.0):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        """INSERT INTO inventory
        (user_id, name, expiration, type, amount, unit, used_count, last_used_month, stable, price_per_unit)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
        (user_id, name, expiration, food_type, amount, unit, date.today().strftime("%Y-%m"), int(stable), price_per_unit),
    )
    conn.commit(); conn.close()

def get_user_items(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, name, expiration, type, amount, unit, used_count, last_used_month, stable, price_per_unit,
               COALESCE(expired_count,0), COALESCE(money_lost,0.0)
        FROM inventory
        WHERE user_id = ?
        ORDER BY date(expiration) ASC, name ASC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def delete_item(item_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    conn.commit(); conn.close()

# ---------- New: Freeze helper ----------
def freeze_item(item_id: int, days: int = 30, label: str = "Frozen"):
    """Extend expiration by N days and tag the item type with 'Frozen' (idempotent)."""
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT name, expiration, type FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close(); raise ValueError("Item not found.")
    name, exp_str, typ = row
    exp = datetime.strptime(exp_str, "%Y-%m-%d").date()
    new_exp = exp + timedelta(days=days)
    new_type = typ if (label in (typ or "")) else f"{typ} • {label}" if typ else label
    c.execute("UPDATE inventory SET expiration = ?, type = ? WHERE id = ?",
              (new_exp.strftime("%Y-%m-%d"), new_type, item_id))
    conn.commit(); conn.close()
    return {"name": name, "new_exp": new_exp.strftime("%Y-%m-%d"), "type": new_type}

# ---------- Util math ----------
def _days_left(exp_str: str) -> int:
    return (datetime.strptime(exp_str, "%Y-%m-%d").date() - date.today()).days

def _status(days_left: int) -> Tuple[str, str]:
    if days_left < 0:  return "Expired", "#FF4B4B"
    if days_left <= 2: return "Expiring Soon", "#FFA500"
    return "Fresh", "#4CAF50"

def _today_ym() -> str:
    return date.today().strftime("%Y-%m")

def _steps_left(amount: float, unit: str) -> float:
    u = (unit or "pcs").lower()
    if u in ("pcs","pc","piece"): return float(amount or 0.0)
    if u in ("g","ml"):           return float(amount or 0.0) / 100.0
    if u in ("kg","l","lt","liter","litre"): return float(amount or 0.0) / 0.1
    return float(amount or 0.0)

def _daily_step_rate(used_steps_this_month: int) -> float:
    d = max(1, date.today().day)
    return (used_steps_this_month or 0) / d

def _runout_eta_str(steps_left: float, daily_rate: float) -> str:
    if daily_rate <= 0 or steps_left <= 0: return "—"
    days = steps_left / daily_rate
    if days < 0.5: return "today"
    if days < 2:   return "≈ 1 day"
    if days < 30:  return f"≈ {int(round(days))} days"
    return f"≈ {int(round(days/30))} mo"

def _value(amount: float, price_per_unit: float) -> float:
    return round((price_per_unit or 0.0) * (amount or 0.0), 2)

def _value_at_risk(items, horizon_days: int) -> float:
    total = 0.0
    for (_id, _name, exp, _type, amount, _unit, *_rest, price, _exp_steps, _lost) in items:
        if _days_left(exp) <= horizon_days:
            total += _value(amount, price)
    return round(total, 2)

# ---------- Smart Coach ----------
def _risk_score(days_left: int, steps_left: float, daily_rate: float) -> float:
    """
    Higher is worse:
      demand_days = steps_left / max(daily_rate, small)
      risk = demand_days - days_left  (positive means likely to expire before consumption)
    Normalize to a 0..100-ish scale.
    """
    dr = daily_rate if daily_rate > 0 else 0.001
    demand_days = steps_left / dr if steps_left > 0 else 0
    gap = demand_days - max(days_left, -7)  # allow negative (already expired) but cap tail
    # map gap into 0..100; 0 means safe (consumed before expiry), 50 borderline, 100 very risky
    score = max(0.0, min(100.0, (gap + 7) * 5))  # crude but effective
    return round(score, 1)

def _auto_plan(rows) -> Dict[str, List[tuple]]:
    """
    Buckets:
      - cook_today: expired or score >= 80 or days_left <= 0
      - cook_48h: score 50..80 or days_left <= 2
      - freeze_now: score >= 70 and price_per_unit > 0
      - safe: everything else
    """
    plan = {"cook_today": [], "cook_48h": [], "freeze_now": [], "safe": []}
    for r in rows:
        (item_id, name, exp, kind, amount, unit, used_count, last_month, stable,
         price_per_unit, expired_steps, money_lost) = r
        days_left = _days_left(exp)
        steps = _steps_left(amount, unit)
        rate = _daily_step_rate(used_count if last_month == _today_ym() else 0)
        score = _risk_score(days_left, steps, rate)
        card = (score, item_id, name, exp, kind, amount, unit, used_count, last_month, stable, price_per_unit, days_left)
        if days_left <= 0 or score >= 80:
            plan["cook_today"].append(card)
        elif score >= 50 or days_left <= 2:
            plan["cook_48h"].append(card)
        elif score >= 70 and (price_per_unit or 0) > 0:
            plan["freeze_now"].append(card)
        else:
            plan["safe"].append(card)
    # sort by score desc inside urgent buckets
    for k in plan:
        plan[k].sort(key=lambda x: (-x[0], x[3]))
    return plan

def _target_stock(used_steps_this_month: int, unit: str, safety_days: int = 3) -> float:
    """Recommend amount to keep on hand (in item's native unit)."""
    rate = _daily_step_rate(used_steps_this_month)
    steps_target = max(1.0, rate * safety_days)
    # convert step count back to native amount
    u = (unit or "pcs").lower()
    if u in ("pcs","pc","piece"): return steps_target
    if u in ("g","ml"):           return steps_target * 100.0
    if u in ("kg","l","lt","liter","litre"): return steps_target * 0.1
    return steps_target

# ---------- Main UI ----------
def inventory():
    st.markdown("<h2 style='text-align:center; color:#FF5A5F;'>📦 Smart Inventory + Smart Coach</h2>", unsafe_allow_html=True)

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please login first from Home.")
        st.stop()
    user_id = st.session_state["user_id"]

    rows = get_user_items(user_id)
    summary = get_monthly_summary(user_id)

    # ======= KPI STRIP =======
    var3, var7, var14 = _value_at_risk(rows, 3), _value_at_risk(rows, 7), _value_at_risk(rows, 14)
    lost_total = round(sum((r[-1] or 0.0) for r in rows), 2)
    k1,k2,k3,k4,k5 = st.columns(5)
    k1.metric("Items", len(rows))
    k2.metric("Value at Risk (3d)", f"₪{var3}")
    k3.metric("Value at Risk (7d)", f"₪{var7}")
    k4.metric("Value at Risk (14d)", f"₪{var14}")
    k5.metric("Money Lost (all‑time)", f"₪{lost_total}")

    # ======= ADD ITEM =======
    st.markdown("### ➕ Add New Item")
    with st.form("add_food_form", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 1.2, 1])
        name = col1.text_input("Food Name", max_chars=50)
        expiration = col2.date_input("Expiration Date", min_value=date.today())
        food_type = col3.selectbox("Type", ["Dairy","Fruit","Meat","Grain","Vegetable","Other"])
        col4, col5, col6 = st.columns([1,1,1])
        amount = col4.number_input("Amount", min_value=0.0, step=1.0, value=1.0)
        unit = col5.selectbox("Unit", ["pcs","g","kg","ml","l"], index=0)
        price = col6.number_input("₪ Price per Unit", min_value=0.0, step=0.1, value=0.0)
        stable = st.checkbox("⚖️ Always Keep in Inventory (Stable Item)")
        if st.form_submit_button("✅ Add to Inventory"):
            if not name.strip(): st.warning("⚠️ Food name is required.")
            else:
                add_item(user_id, name.strip(), expiration.strftime("%Y-%m-%d"), food_type, float(amount), unit, stable, float(price))
                st.success(f"Added {amount} {unit} of {name}.")
                st.rerun()

    # ======= SMART COACH =======
    st.markdown("### 🧠 Smart Coach: What to do now")
    plan = _auto_plan(rows)
    cA,cB,cC,cD = st.columns(4)
    cA.markdown(f"**Cook today ({len(plan['cook_today'])})**")
    cB.markdown(f"**Cook in 48h ({len(plan['cook_48h'])})**")
    cC.markdown(f"**Freeze now ({len(plan['freeze_now'])})**")
    cD.markdown(f"**Safe ({len(plan['safe'])})**")

    # Batch toolbars for each urgent bucket
    bt1, bt2, bt3 = st.columns([1.5,1.5,3])
    if bt1.button("✅ Use 1 step for all 'Cook today'"):
        for score, item_id, *_ in plan["cook_today"]:
            try: use_one_step(item_id)
            except Exception as e: st.error(f"Use failed (id {item_id}): {e}")
        st.rerun()
    if bt2.button("🧊 Freeze all 'Freeze now' (+30d)"):
        for score, item_id, *_ in plan["freeze_now"]:
            try: freeze_item(item_id, days=30)
            except Exception as e: st.error(f"Freeze failed (id {item_id}): {e}")
        st.rerun()

    # ======= LIST WITH CARDS =======
    st.markdown("### 📋 Inventory")
    if not rows:
        st.info("🪹 Empty. Add something before the fridge becomes a museum.")
        return

    colA, colB = st.columns(2)
    for idx, r in enumerate(rows):
        (item_id, name, exp, kind, amount, unit, used_count, last_month, stable,
         price_per_unit, expired_steps, money_lost) = r
        dleft = _days_left(exp)
        status, color = _status(dleft)
        steps = _steps_left(amount, unit)
        rate = _daily_step_rate(used_count if last_month == _today_ym() else 0)
        eta = _runout_eta_str(steps, rate)
        score = _risk_score(dleft, steps, rate)

        host = colA if idx % 2 == 0 else colB
        with host:
            st.markdown(f"""
                <div style='background:#1f1f1f;border-left:6px solid {color};padding:14px 16px;border-radius:12px;margin-bottom:12px'>
                    <h4 style='margin:0;color:#FAFAFA'>{name} <span style='font-size:12px;color:#888;'>({kind})</span></h4>
                    <p style='margin:4px 0;color:#CCC;'>📅 <b>Expires:</b> {exp} &nbsp; | &nbsp; 🔔 <b>{status}</b> &nbsp; | &nbsp; 🧮 <b>Risk:</b> {score}</p>
                    <p style='margin:4px 0;color:#CCC;'>🔢 <b>Amount:</b> {amount} {unit} &nbsp; | &nbsp; 💲 <b>₪/unit:</b> {price_per_unit} &nbsp; | &nbsp; ⏳ <b>ETA:</b> {eta}</p>
                    <p style='margin:4px 0;color:#CCC;'>✅ <b>Used this month:</b> {used_count} &nbsp; | &nbsp; 🗑️ <b>Expired steps:</b> {expired_steps} &nbsp; | &nbsp; 💸 <b>Lost:</b> ₪{round(money_lost or 0.0,2)}</p>
                    {"<p style='margin:4px 0;color:#0ff;'>⚖️ <b>Stable Item</b></p>" if stable else ""}
                </div>
            """, unsafe_allow_html=True)

            # Quick actions row
            c1,c2,c3,c4,c5 = st.columns([1.2,1.2,1.2,1.2,1.2])
            if c1.button("✅ Use 1", key=f"use1_{item_id}"):
                try:
                    res = use_one_step(item_id)
                    st.success(f"Used +1 step (−{res['deducted']} {res['unit']}). Remaining {res['remaining']} {res['unit']}.")
                except Exception as e:
                    st.error(f"Use failed: {e}")
                st.rerun()

            step = 0.1 if unit in ("kg","l","lt","liter","litre") else (100.0 if unit in ("g","ml") else 1.0)
            qty = c2.number_input("Qty", min_value=0.0, step=step, key=f"qty_{item_id}")

            if c3.button("🍴 Use qty", key=f"useqty_{item_id}"):
                try:
                    res = use_item(item_id, float(qty))
                    st.success(f"Used +{res['used_step_added']} steps. Remaining {res['remaining']} {res['unit']}.")
                except Exception as e:
                    st.error(f"Use qty failed: {e}")
                st.rerun()

            if c4.button("🧪 Expire qty", key=f"expqty_{item_id}"):
                try:
                    res = expire_item(item_id, float(qty))
                    st.warning(f"Expired +{res['expired_step_added']} steps. Lost total ₪{res['lost_nis_total']}. Remaining {res['remaining']} {res['unit']}.")
                except Exception as e:
                    st.error(f"Expire qty failed: {e}")
                st.rerun()

            if c5.button("☠️ Expire ALL", key=f"expall_{item_id}"):
                try:
                    res = expire_all(item_id)
                    st.error(f"Expired whole item: +{res['expired_step_added']} steps. Lost total ₪{res['lost_nis_total']}.")
                except Exception as e:
                    st.error(f"Expire all failed: {e}")
                st.rerun()

            # Second row: Freeze, Edit, Delete
            d1,d2,d3 = st.columns([1.2,1.2,1])
            if d1.button("🧊 Freeze +30d", key=f"freeze_{item_id}"):
                try:
                    info = freeze_item(item_id, days=30)
                    st.info(f"Extended to {info['new_exp']} ({info['type']}).")
                except Exception as e:
                    st.error(f"Freeze failed: {e}")
                st.rerun()

            with d2.expander("✏️ Edit"):
                new_name = st.text_input("Name", value=name, key=f"nm_{item_id}")
                new_exp = st.date_input("Expiration", value=datetime.strptime(exp, "%Y-%m-%d").date(), key=f"ex_{item_id}")
                new_type = st.text_input("Type", value=kind, key=f"tp_{item_id}")
                new_amt = st.number_input("Amount", min_value=0.0, value=float(amount), step=step, key=f"am_{item_id}")
                new_unit = st.selectbox("Unit", ["pcs","g","kg","ml","l"],
                                        index=["pcs","g","kg","ml","l"].index(unit) if unit in ["pcs","g","kg","ml","l"] else 0,
                                        key=f"un_{item_id}")
                new_price = st.number_input("₪ Price per Unit", min_value=0.0, value=float(price_per_unit or 0.0), step=0.1, key=f"pr_{item_id}")
                if st.button("💾 Save", key=f"save_{item_id}"):
                    try:
                        db_update_item(item_id, new_name.strip(), new_exp.strftime("%Y-%m-%d"), new_type, float(new_amt), new_unit, float(new_price))
                        st.success("Saved.")
                    except Exception as e:
                        st.error(f"Save failed: {e}")
                    st.rerun()

            if d3.button("🗑️ Delete", key=f"del_{item_id}"):
                delete_item(item_id); st.rerun()

    # ======= SHOPPING OPTIMIZER =======
    st.markdown("### 🛒 Shopping Optimizer (3‑day safety)")
    if rows:
        import math
        colH = st.columns(5)
        colH[0].markdown("**Item**")
        colH[1].markdown("**Current**")
        colH[2].markdown("**Target**")
        colH[3].markdown("**Δ (buy + / reduce −)**")
        colH[4].markdown("**₪ Impact**")

        total_delta_cost = 0.0
        for r in rows:
            (item_id, name, exp, kind, amount, unit, used_count, last_month, stable,
             price_per_unit, expired_steps, money_lost) = r
            steps_target_amt = _target_stock(used_count if last_month == _today_ym() else 0, unit, safety_days=3)
            delta = round(steps_target_amt - float(amount or 0.0), 2)
            cost = round(delta * float(price_per_unit or 0.0), 2)
            total_delta_cost += cost
            c = st.columns(5)
            c[0].write(name)
            c[1].write(f"{amount} {unit}")
            c[2].write(f"{round(steps_target_amt,2)} {unit}")
            c[3].write(("+" if delta > 0 else "") + str(delta))
            c[4].write(("+" if cost > 0 else "") + f"₪{cost}")
        st.caption(f"Estimated basket change to hit 3‑day buffer: **₪{round(total_delta_cost,2)}**")
