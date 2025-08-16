# SmartCoach.py — KPIs, bounded risk, real buckets, freeze (uses frozen_until), batch, optional AI explainer
import os
import math
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple

import streamlit as st
from db import get_connection, use_one_step, expire_all, get_monthly_summary

# -----------------------------
# DB access
# -----------------------------
def get_user_items(user_id: int):
    """
    Return rows with all fields the coach needs, sorted by effective expiry (frozen_until > expiration).
    """
    conn = get_connection(); c = conn.cursor()
    c.execute("""
        SELECT
            id,                -- 0
            name,              -- 1
            expiration,        -- 2
            type,              -- 3
            amount,            -- 4
            unit,              -- 5
            used_count,        -- 6
            last_used_month,   -- 7
            stable,            -- 8
            price_per_unit,    -- 9
            COALESCE(expired_count,0), -- 10
            COALESCE(money_lost,0.0),  -- 11
            frozen_until,      -- 12
            COALESCE(perishability,2)  -- 13 (1=low,2=med,3=high)
        FROM inventory
        WHERE user_id=?
        ORDER BY date(COALESCE(frozen_until, expiration)) ASC, name ASC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def freeze_item(item_id: int, days: int = 30, label: str = "Frozen"):
    """
    Extend shelf-life by setting frozen_until. Do not rewrite the real expiration date.
    """
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT expiration, type FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise ValueError("Item not found")

    exp_str, typ = row
    base = datetime.strptime(exp_str, "%Y-%m-%d").date()
    new_until = (base + timedelta(days=days)).strftime("%Y-%m-%d")
    new_type = typ if (typ and label in typ) else (f"{typ} • {label}" if typ else label)

    c.execute("UPDATE inventory SET frozen_until=?, type=? WHERE id=?", (new_until, new_type, item_id))
    conn.commit(); conn.close()
    return new_until, new_type

# -----------------------------
# Helpers
# -----------------------------
def _today_ym() -> str:
    return date.today().strftime("%Y-%m")

def _effective_expiry(exp_str: str, frozen_until: str | None) -> date:
    base = datetime.strptime(exp_str, "%Y-%m-%d").date()
    if frozen_until:
        fu = datetime.strptime(frozen_until, "%Y-%m-%d").date()
        if fu > base:
            return fu
    return base

def _days_left_pair(exp_str: str, frozen_until: str | None) -> int:
    return (_effective_expiry(exp_str, frozen_until) - date.today()).days

def _steps_left(amount: float, unit: str) -> float:
    u = (unit or "pcs").lower()
    amt = float(amount or 0.0)
    if u in ("pcs", "pc", "piece"):            return amt
    if u in ("g", "ml"):                       return amt / 100.0     # 100 g/ml per step
    if u in ("kg", "l", "lt", "liter", "litre"): return amt / 0.1     # 0.1 kg/L per step
    return amt

def _daily_rate(used_steps_this_month: int) -> float:
    day = max(1, date.today().day)
    real = (used_steps_this_month or 0) / day
    return real if real > 0 else 0.5  # gentle floor to avoid infinity

def _value_nis(amount: float, ppu: float) -> float:
    return round((ppu or 0.0) * (amount or 0.0), 2)

def _value_at_risk(rows, horizon_days: int) -> float:
    total = 0.0
    for r in rows:
        amount, ppu = r[4], r[9]
        exp_str, frozen_until = r[2], r[12]
        if _days_left_pair(exp_str, frozen_until) <= horizon_days:
            total += (ppu or 0.0) * (amount or 0.0)
    return round(total, 2)

def _risk_score(days_left: int, steps_left: float, daily_rate: float, value_nis: float, perishability: int) -> int:
    """
    Bounded 0..100 score combining time urgency, demand pressure, money at risk and perishability.
    """
    # Time urgency
    urgency = max(0.0, min(1.0, (14.0 - days_left) / 14.0))  # <=0 days -> 1.0

    # Demand pressure (stock weeks vs rate)
    rate = max(daily_rate, 0.1)
    stock_weeks = (steps_left / rate) / 7.0 if steps_left > 0 else 0.0
    demand = max(0.0, min(1.0, 1.0 - min(stock_weeks, 1.0)))  # <=1 week -> 1.0

    # Money influence (diminishing)
    value = max(0.0, min(1.0, math.log1p(max(value_nis, 0.0)) / 5.0))

    perish_w = {1: 0.30, 2: 0.65, 3: 1.00}.get(int(perishability or 2), 0.65)

    score = 100 * (0.55 * urgency + 0.25 * demand + 0.20 * value * perish_w)
    return int(round(max(0.0, min(100.0, score))))

# -----------------------------
# Optional OpenAI explainer
# -----------------------------
def _ai_explain(plan_summary: Dict[str, List[Tuple]]):
    api_key = os.getenv("OPENAI_API_KEY") or st.secrets.get("OPENAI_API_KEY", None)
    if not api_key:
        return None
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
    except Exception:
        return None

    def join_names(items, n=6):
        names = [x[2] for x in items][:n]
        extra = max(0, len(items) - n)
        return ", ".join(names) + (f" +{extra} more" if extra else "")

    prompt = (
        "You are an inventory coach. Summarize the action plan concisely with reasons and tips.\n\n"
        f"Cook today: {join_names(plan_summary['cook_today'])}\n"
        f"Cook in 48h: {join_names(plan_summary['cook_48h'])}\n"
        f"Freeze now: {join_names(plan_summary['freeze_now'])}\n"
        f"Safe: {join_names(plan_summary['safe'])}\n\n"
        "Be practical. 4-6 bullet points max. Mention perishables vs pantry if relevant."
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=220,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return None

# -----------------------------
# UI
# -----------------------------
def coach():
    st.title("🧠 Smart Coach")
    # version banner helps verify hot reloads
    st.caption("build R8 • risk=v2 • frozen_until enabled")

    if "user_id" not in st.session_state:
        st.warning("Login first."); st.stop()
    user_id = st.session_state["user_id"]

    rows = get_user_items(user_id)
    if not rows:
        st.info("Nothing to analyze. Add items in Inventory."); return

    # KPIs
    var3, var7, var14 = _value_at_risk(rows, 3), _value_at_risk(rows, 7), _value_at_risk(rows, 14)
    lost_total = round(sum((r[11] or 0.0) for r in rows), 2)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Items", len(rows))
    k2.metric("Value at Risk (3d)", f"₪{var3}")
    k3.metric("Value at Risk (7d)", f"₪{var7}")
    k4.metric("Value at Risk (14d)", f"₪{var14}")
    k5.metric("Money Lost (all-time)", f"₪{lost_total}")

    # Auto plan
    plan: Dict[str, List[Tuple]] = {"cook_today": [], "cook_48h": [], "freeze_now": [], "safe": []}

    for r in rows:
        (
            item_id, name, exp, typ, amount, unit, used_count, last_m, stable,
            ppu, _, _, frozen_until, perishability
        ) = r

        dl = _days_left_pair(exp, frozen_until)
        steps = _steps_left(amount, unit)
        rate = _daily_rate(used_count if last_m == _today_ym() else 0)
        value = _value_nis(amount, ppu)
        score = _risk_score(dl, steps, rate, value, perishability)

        card = (score, item_id, name, exp, typ, amount, unit, used_count, last_m, stable, ppu, dl, frozen_until, perishability, value)

        if dl <= 1 or score >= 85:
            plan["cook_today"].append(card)
        elif 2 <= dl <= 3 or 70 <= score < 85:
            plan["cook_48h"].append(card)
        elif (perishability == 3 and dl <= 3) or (score >= 80 and value > 0):
            plan["freeze_now"].append(card)
        else:
            plan["safe"].append(card)

    for k in plan:
        plan[k].sort(key=lambda x: (-x[0], x[12], x[2]))

    st.subheader("Plan")
    cA, cB, cC, cD = st.columns(4)
    cA.metric("Cook today", len(plan["cook_today"]))
    cB.metric("Cook in 48h", len(plan["cook_48h"]))
    cC.metric("Freeze now", len(plan["freeze_now"]))
    cD.metric("Safe", len(plan["safe"]))

    # Batch actions
    b1, b2 = st.columns(2)
    if b1.button("✅ Use 1 step for all 'Cook today'"):
        for score, item_id, *_ in plan["cook_today"]:
            try:
                use_one_step(item_id)
            except Exception as e:
                st.error(f"id {item_id}: {e}")
        st.rerun()

    if b2.button("🧊 Freeze all 'Freeze now' (+30d)"):
        for score, item_id, *_ in plan["freeze_now"]:
            try:
                freeze_item(item_id, 30)
            except Exception as e:
                st.error(f"id {item_id}: {e}")
        st.rerun()

    # Optional AI explainer
    expl = _ai_explain(plan)
    if expl:
        with st.expander("💡 Coach notes"):
            st.markdown(expl)

    # Lists
    def badge(score: int) -> str:
        if score >= 85: return "🟥 High"
        if score >= 70: return "🟧 Med"
        if score >= 50: return "🟨 Watch"
        return "🟩 Low"

    def bucket_ui(title: str, items: List[Tuple]):
        st.markdown(f"#### {title}")
        if not items:
            st.caption("Nothing here."); return
        for (score, item_id, name, exp, typ, amount, unit, used_count, last_m, stable, ppu, dl, frozen_until, perish, value) in items:
            eff = _effective_expiry(exp, frozen_until).strftime("%Y-%m-%d")
            with st.container(border=True):
                st.write(
                    f"**{name}** ({typ or '—'}) • Value: ₪{value:.2f} • Perish: {perish} "
                    f"| Expires: {eff} | Left: {amount} {unit} | ₪/unit: {ppu or 0}"
                )
                st.write(f"Risk: **{score}** {badge(score)} | Days left: {dl} | Used this month: {used_count}")
                st.progress(min(100, max(0, score)) / 100.0)

                c1, c2, c3 = st.columns([1, 1, 1])
                if c1.button("✅ Use 1", key=f"use1_{item_id}"):
                    try:
                        use_one_step(item_id); st.success("Used 1."); st.rerun()
                    except Exception as e:
                        st.error(e)
                if c2.button("🧊 Freeze +30d", key=f"fr_{item_id}"):
                    try:
                        new_until, _ = freeze_item(item_id, 30)
                        st.info(f"Frozen until {new_until}"); st.rerun()
                    except Exception as e:
                        st.error(e)
                if c3.button("☠️ Expire ALL", key=f"exall_{item_id}"):
                    try:
                        expire_all(item_id); st.error("Expired all."); st.rerun()
                    except Exception as e:
                        st.error(e)

    bucket_ui("Cook today", plan["cook_today"])
    bucket_ui("Cook in 48 hours", plan["cook_48h"])
    bucket_ui("Freeze now", plan["freeze_now"])
    bucket_ui("Safe", plan["safe"])
