# SmartCoach.py — KPIs, risk scoring, auto plan, freeze, batch
import streamlit as st
from datetime import datetime, date, timedelta
from typing import Tuple, Dict, List
from db import get_connection, use_one_step, expire_all, get_monthly_summary

def get_user_items(user_id):
    conn = get_connection(); c = conn.cursor()
    c.execute("""SELECT id,name,expiration,type,amount,unit,used_count,last_used_month,stable,price_per_unit,
                        COALESCE(expired_count,0), COALESCE(money_lost,0.0)
                 FROM inventory WHERE user_id=? ORDER BY date(expiration) ASC, name ASC""", (user_id,))
    rows = c.fetchall(); conn.close(); return rows

def freeze_item(item_id: int, days: int = 30, label: str = "Frozen"):
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT expiration,type FROM inventory WHERE id=?", (item_id,))
    exp_str, typ = c.fetchone()
    new_exp = datetime.strptime(exp_str,"%Y-%m-%d").date() + timedelta(days=days)
    new_type = typ if (label in (typ or "")) else f"{typ} • {label}" if typ else label
    c.execute("UPDATE inventory SET expiration=?, type=? WHERE id=?", (new_exp.strftime("%Y-%m-%d"), new_type, item_id))
    conn.commit(); conn.close()
    return new_exp.strftime("%Y-%m-%d"), new_type

def _days_left(exp_str: str) -> int:
    return (datetime.strptime(exp_str, "%Y-%m-%d").date() - date.today()).days

def _today_ym() -> str:
    return date.today().strftime("%Y-%m")

def _steps_left(amount: float, unit: str) -> float:
    u = (unit or "pcs").lower()
    if u in ("pcs","pc","piece"): return float(amount or 0.0)
    if u in ("g","ml"):           return float(amount or 0.0)/100.0
    if u in ("kg","l","lt","liter","litre"): return float(amount or 0.0)/0.1
    return float(amount or 0.0)

def _daily_rate(used_steps_this_month: int) -> float:
    d = max(1, date.today().day)
    return (used_steps_this_month or 0)/d

def _risk_score(days_left: int, steps_left: float, daily_rate: float) -> float:
    dr = daily_rate if daily_rate > 0 else 0.001
    demand_days = steps_left/dr if steps_left>0 else 0
    gap = demand_days - max(days_left, -7)
    return round(max(0,min(100,(gap+7)*5)),1)

def _value(amount: float, ppu: float) -> float:
    return round((ppu or 0.0)*(amount or 0.0),2)

def _value_at_risk(rows, horizon_days: int) -> float:
    return round(sum(_value(r[4], r[9]) for r in rows if _days_left(r[2])<=horizon_days), 2)

def coach():
    st.title("🧠 Smart Coach")
    if "user_id" not in st.session_state:
        st.warning("Login first."); st.stop()
    user_id = st.session_state["user_id"]

    rows = get_user_items(user_id)
    if not rows:
        st.info("Nothing to analyze. Add items in Inventory."); return

    # KPIs
    var3, var7, var14 = _value_at_risk(rows,3), _value_at_risk(rows,7), _value_at_risk(rows,14)
    lost_total = round(sum((r[-1] or 0.0) for r in rows), 2)
    k1,k2,k3,k4,k5 = st.columns(5)
    k1.metric("Items", len(rows))
    k2.metric("Value at Risk (3d)", f"₪{var3}")
    k3.metric("Value at Risk (7d)", f"₪{var7}")
    k4.metric("Value at Risk (14d)", f"₪{var14}")
    k5.metric("Money Lost (all‑time)", f"₪{lost_total}")

    # Auto plan
    plan = {"cook_today":[], "cook_48h":[], "freeze_now":[], "safe":[]}
    for r in rows:
        (item_id, name, exp, typ, amount, unit, used_count, last_m, stable, ppu, exp_steps, money_lost) = r
        dl = _days_left(exp)
        steps = _steps_left(amount, unit)
        rate = _daily_rate(used_count if last_m == _today_ym() else 0)
        score = _risk_score(dl, steps, rate)
        card = (score, item_id, name, exp, typ, amount, unit, used_count, last_m, stable, ppu, dl)
        if dl <= 0 or score >= 80: plan["cook_today"].append(card)
        elif score >= 50 or dl <= 2: plan["cook_48h"].append(card)
        elif score >= 70 and (ppu or 0) > 0: plan["freeze_now"].append(card)
        else: plan["safe"].append(card)
    for k in plan: plan[k].sort(key=lambda x: (-x[0], x[3]))

    st.subheader("Plan")
    cA,cB,cC,cD = st.columns(4)
    cA.metric("Cook today", len(plan["cook_today"]))
    cB.metric("Cook in 48h", len(plan["cook_48h"]))
    cC.metric("Freeze now", len(plan["freeze_now"]))
    cD.metric("Safe", len(plan["safe"]))

    # Batch actions
    b1,b2 = st.columns(2)
    if b1.button("✅ Use 1 step for all 'Cook today'"):
        for score, item_id, *_ in plan["cook_today"]:
            try: use_one_step(item_id)
            except Exception as e: st.error(f"id {item_id}: {e}")
        st.rerun()
    if b2.button("🧊 Freeze all 'Freeze now' (+30d)"):
        for score, item_id, *_ in plan["freeze_now"]:
            try: freeze_item(item_id, 30)
            except Exception as e: st.error(f"id {item_id}: {e}")
        st.rerun()

    # Lists
    def bucket_ui(title, items):
        st.markdown(f"#### {title}")
        if not items: st.caption("Nothing here."); return
        for score, item_id, name, exp, typ, amount, unit, used_count, last_m, stable, ppu, dl in items:
            with st.container(border=True):
                st.write(f"**{name}** ({typ})  |  Expires: {exp}  |  Amount: {amount} {unit}  |  ₪/unit: {ppu}")
                st.write(f"Risk: **{score}**  |  Days left: {dl}  |  Used this month: {used_count}")
                c1,c2,c3 = st.columns([1,1,1])
                if c1.button("✅ Use 1", key=f"use1_{item_id}"):
                    try: use_one_step(item_id); st.success("Used 1."); st.rerun()
                    except Exception as e: st.error(e)
                if c2.button("🧊 Freeze +30d", key=f"fr_{item_id}"):
                    try: new_exp,_ = freeze_item(item_id, 30); st.info(f"New exp {new_exp}"); st.rerun()
                    except Exception as e: st.error(e)
                if c3.button("☠️ Expire ALL", key=f"exall_{item_id}"):
                    try: expire_all(item_id); st.error("Expired all."); st.rerun()
                    except Exception as e: st.error(e)

    bucket_ui("Cook today", plan["cook_today"])
    bucket_ui("Cook in 48 hours", plan["cook_48h"])
    bucket_ui("Freeze now", plan["freeze_now"])
    bucket_ui("Safe", plan["safe"])
