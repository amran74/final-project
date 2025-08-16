# SmartCoach.py — R10: schema-self-heal, bounded risk, frozen_until, buckets, debug, safe fallbacks

import os
import math
from datetime import datetime, date, timedelta
from typing import Dict, List, Tuple, Optional

import streamlit as st

# --- Try your db helpers; fall back to safe local ops if missing ---
try:
    from db import get_connection, use_one_step, expire_all, get_monthly_summary  # type: ignore
except Exception:
    import sqlite3
    def get_connection():
        return sqlite3.connect("inventory.db")

    def use_one_step(item_id: int):
        conn = get_connection(); c = conn.cursor()
        c.execute("UPDATE inventory SET amount=MAX(0, COALESCE(amount,0)-1), "
                  "used_count=COALESCE(used_count,0)+1, "
                  "last_used_month=strftime('%Y-%m','now') WHERE id=?", (item_id,))
        conn.commit(); conn.close()

    def expire_all(item_id: int):
        conn = get_connection(); c = conn.cursor()
        c.execute("SELECT COALESCE(price_per_unit,0), COALESCE(amount,0) FROM inventory WHERE id=?", (item_id,))
        row = c.fetchone()
        lost = (row[0] * row[1]) if row else 0.0
        c.execute("UPDATE inventory SET amount=0, "
                  "expired_count=COALESCE(expired_count,0)+1, "
                  "money_lost=COALESCE(money_lost,0)+? WHERE id=?", (lost, item_id))
        conn.commit(); conn.close()

    def get_monthly_summary(user_id: int):
        return {}

# -----------------------------
# Defensive schema migration
# -----------------------------
def _ensure_column(conn, table: str, column: str, ddl: str):
    c = conn.cursor()
    c.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in c.fetchall()]
    if column not in cols:
        c.execute(ddl)
        conn.commit()

def _migrate_schema():
    conn = get_connection()
    try:
        _ensure_column(conn, "inventory", "used_count",
                       "ALTER TABLE inventory ADD COLUMN used_count INTEGER DEFAULT 0")
        _ensure_column(conn, "inventory", "last_used_month",
                       "ALTER TABLE inventory ADD COLUMN last_used_month TEXT DEFAULT ''")
        _ensure_column(conn, "inventory", "expired_count",
                       "ALTER TABLE inventory ADD COLUMN expired_count INTEGER DEFAULT 0")
        _ensure_column(conn, "inventory", "money_lost",
                       "ALTER TABLE inventory ADD COLUMN money_lost REAL DEFAULT 0")
        _ensure_column(conn, "inventory", "price_per_unit",
                       "ALTER TABLE inventory ADD COLUMN price_per_unit REAL DEFAULT 0")
        _ensure_column(conn, "inventory", "stable",
                       "ALTER TABLE inventory ADD COLUMN stable INTEGER DEFAULT 0")
        _ensure_column(conn, "inventory", "frozen_until",
                       "ALTER TABLE inventory ADD COLUMN frozen_until TEXT")
        _ensure_column(conn, "inventory", "perishability",
                       "ALTER TABLE inventory ADD COLUMN perishability INTEGER DEFAULT 2")
    finally:
        conn.close()

# -----------------------------
# Parsing and helpers
# -----------------------------
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y")

def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    s = str(s).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None  # bad format

def _today_ym() -> str:
    return date.today().strftime("%Y-%m")

def _effective_expiry(exp_str: str, frozen_until: Optional[str]) -> date:
    base = _parse_date(exp_str) or date.today() + timedelta(days=3650)  # push far if corrupt
    if frozen_until:
        fu = _parse_date(frozen_until)
        if fu and fu > base:
            return fu
    return base

def _days_left_pair(exp_str: str, frozen_until: Optional[str]) -> int:
    return (_effective_expiry(exp_str, frozen_until) - date.today()).days

def _steps_left(amount: float, unit: Optional[str]) -> float:
    u = (unit or "pcs").lower()
    amt = float(amount or 0.0)
    if u in ("pcs", "pc", "piece"): return amt
    if u in ("g", "ml"): return amt / 100.0          # ~100g/ml per step
    if u in ("kg", "l", "lt", "liter", "litre"): return amt / 0.1  # ~0.1 kg/L per step
    return amt

def _daily_rate(used_steps_this_month: int) -> float:
    day = max(1, date.today().day)
    real = (used_steps_this_month or 0) / day
    return real if real > 0 else 0.5  # gentle floor to avoid infinity

def _value_nis(amount: float, ppu: float) -> float:
    return round((ppu or 0.0) * (amount or 0.0), 2)

def _risk_score(days_left: int, steps_left: float, daily_rate: float, value_nis: float, perishability: int) -> int:
    # Time urgency 0..1 (dominant)
    urgency = max(0.0, min(1.0, (14.0 - days_left) / 14.0))  # <=0 => 1.0
    # Demand pressure: weeks of stock vs rate
    rate = max(daily_rate, 0.1)
    stock_weeks = (steps_left / rate) / 7.0 if steps_left > 0 else 0.0
    demand = max(0.0, min(1.0, 1.0 - min(stock_weeks, 1.0)))  # <=1 week => 1.0
    # Money influence, diminishing returns
    value = max(0.0, min(1.0, math.log1p(max(value_nis, 0.0)) / 5.0))
    perish_w = {1: 0.30, 2: 0.65, 3: 1.00}.get(int(perishability or 2), 0.65)
    score = 100 * (0.55 * urgency + 0.25 * demand + 0.20 * value * perish_w)
    return int(round(max(0.0, min(100.0, score))))

# -----------------------------
# DB access
# -----------------------------
def get_user_items(user_id: int):
    """Selects with defensive COALESCE so missing columns never crash us."""
    conn = get_connection(); c = conn.cursor()
    c.execute("""
        SELECT
            id,                     -- 0
            name,                   -- 1
            expiration,             -- 2
            COALESCE(type,'') as type,          -- 3
            COALESCE(amount,0) as amount,       -- 4
            COALESCE(unit,'pcs') as unit,       -- 5
            COALESCE(used_count,0),             -- 6
            COALESCE(last_used_month,''),       -- 7
            COALESCE(stable,0),                 -- 8
            COALESCE(price_per_unit,0),         -- 9
            COALESCE(expired_count,0),          -- 10
            COALESCE(money_lost,0),             -- 11
            frozen_until,                        -- 12
            COALESCE(perishability,2)           -- 13
        FROM inventory
        WHERE user_id=?
        ORDER BY date(COALESCE(frozen_until, expiration)) ASC, name ASC
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def freeze_item(item_id: int, days: int = 30, label: str = "Frozen"):
    """Set frozen_until without touching the real expiration."""
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT expiration, COALESCE(type,'') FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        raise ValueError("Item not found")
    exp_str, typ = row
    base = _parse_date(exp_str) or date.today()
    new_until = (base + timedelta(days=days)).strftime("%Y-%m-%d")
    new_type = typ if (typ and label in typ) else (f"{typ} • {label}" if typ else label)
    c.execute("UPDATE inventory SET frozen_until=?, type=? WHERE id=?", (new_until, new_type, item_id))
    conn.commit(); conn.close()
    return new_until, new_type

# -----------------------------
# UI
# -----------------------------
def coach():
    st.title("🧠 Smart Coach")
    st.caption("SmartCoach R10 • self-heal schema • risk=v2 • frozen_until enabled")

    if "user_id" not in st.session_state:
        st.warning("Login first."); st.stop()
    user_id = int(st.session_state["user_id"])

    # Ensure required columns exist even if your DB is ancient
    _migrate_schema()

    rows = get_user_items(user_id)
    if not rows:
        st.info("Nothing to analyze. Add items in Inventory."); return

    # KPIs: value-at-risk on effective expiry
    def _value_at_risk(horizon_days: int) -> float:
        total = 0.0
        for r in rows:
            amount, ppu = r[4], r[9]
            if _days_left_pair(r[2], r[12]) <= horizon_days:
                total += (ppu or 0.0) * (amount or 0.0)
        return round(total, 2)

    var3, var7, var14 = _value_at_risk(3), _value_at_risk(7), _value_at_risk(14)
    lost_total = round(sum((r[11] or 0.0) for r in rows), 2)

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Items", len(rows))
    k2.metric("Value at Risk (3d)", f"₪{var3}")
    k3.metric("Value at Risk (7d)", f"₪{var7}")
    k4.metric("Value at Risk (14d)", f"₪{var14}")
    k5.metric("Money Lost (all-time)", f"₪{lost_total}")

    # Build plan
    plan: Dict[str, List[Tuple]] = {"cook_today": [], "cook_48h": [], "freeze_now": [], "safe": []}
    cards: List[Tuple] = []

    for r in rows:
        (item_id, name, exp, typ, amount, unit, used_count, last_m, stable,
         ppu, exp_steps, money_lost, frozen_until, perishability) = r

        dl = _days_left_pair(exp, frozen_until)
        steps = _steps_left(amount, unit)
        rate = _daily_rate(used_count if last_m == _today_ym() else 0)
        value = _value_nis(amount, ppu)
        score = _risk_score(dl, steps, rate, value, perishability)

        card = (score, item_id, name, exp, typ, amount, unit, used_count, last_m,
                stable, ppu, dl, frozen_until, perishability, value)
        cards.append(card)

        if dl <= 1 or score >= 85:
            plan["cook_today"].append(card)
        elif 2 <= dl <= 3 or 70 <= score < 85:
            plan["cook_48h"].append(card)
        elif (perishability == 3 and dl <= 3) or (score >= 80 and value > 0):
            plan["freeze_now"].append(card)
        else:
            plan["safe"].append(card)

    for k in plan:
        plan[k].sort(key=lambda x: (-x[0], x[12], x[2]))  # risk desc, earliest effective expiry, name

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
            try: use_one_step(item_id)
            except Exception as e: st.error(f"id {item_id}: {e}")
        st.rerun()

    if b2.button("🧊 Freeze all 'Freeze now' (+30d)"):
        for score, item_id, *_ in plan["freeze_now"]:
            try: freeze_item(item_id, 30)
            except Exception as e: st.error(f"id {item_id}: {e}")
        st.rerun()

    # DEBUG: show scoring inputs so you can verify reality
    with st.expander("DEBUG: scoring inputs (first 25)"):
        import pandas as pd
        rows_dbg = []
        for (score, item_id, name, exp, typ, amount, unit, used_count, last_m,
             stable, ppu, dl, frozen_until, perish, value) in cards[:25]:
            rate = _daily_rate(used_count if last_m == _today_ym() else 0)
            steps = _steps_left(amount, unit)
            # components (for your sanity)
            urg = max(0.0, min(1.0, (14.0 - dl) / 14.0))
            rrate = max(rate, 0.1)
            stock_weeks = (steps / rrate) / 7.0 if steps > 0 else 0.0
            dem = max(0.0, min(1.0, 1.0 - min(stock_weeks, 1.0)))
            valc = max(0.0, min(1.0, math.log1p(max(value, 0.0)) / 5.0))
            rows_dbg.append([
                item_id, name, exp, frozen_until, dl, steps, round(rate,3),
                value, perish, round(urg,3), round(dem,3), round(valc,3), score
            ])
        df = pd.DataFrame(rows_dbg, columns=[
            "id","name","exp","frozen_until","days_left","steps","daily_rate","₪value","perish",
            "urgency","demand","value_comp","score"
        ])
        st.dataframe(df, use_container_width=True)

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
        for (score, item_id, name, exp, typ, amount, unit, used_count, last_m,
             stable, ppu, dl, frozen_until, perish, value) in items:
            eff = _effective_expiry(exp, frozen_until).strftime("%Y-%m-%d")
            with st.container(border=True):
                st.write(
                    f"**{name}** ({typ or '—'}) • Value: ₪{value:.2f} • Perish: {perish} "
                    f"| Expires: {eff} | Left: {amount} {unit} | ₪/unit: {ppu or 0}"
                )
                st.write(f"Risk: **{score}** {badge(score)} | Days left: {dl} | Used this month: {used_count}")
                st.progress(min(100, max(0, score)) / 100.0)
                c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
                if c1.button("✅ Use 1", key=f"use1_{item_id}"):
                    try: use_one_step(item_id); st.success("Used 1."); st.rerun()
                    except Exception as e: st.error(e)
                if c2.button("🧊 Freeze +30d", key=f"fr_{item_id}"):
                    try: new_until, _ = freeze_item(item_id, 30); st.info(f"Frozen until {new_until}"); st.rerun()
                    except Exception as e: st.error(e)
                if c3.button("☠️ Expire ALL", key=f"exall_{item_id}"):
                    try: expire_all(item_id); st.error("Expired all."); st.rerun()
                    except Exception as e: st.error(e)
                # Quick tweak perishability inline (1..3) to tune risk properly
                new_p = c4.selectbox("Perish", [1,2,3], index=max(1, min(3, int(perish)))-1, key=f"per_{item_id}")
                if new_p != perish:
                    conn = get_connection(); cc = conn.cursor()
                    cc.execute("UPDATE inventory SET perishability=? WHERE id=?", (int(new_p), item_id))
                    conn.commit(); conn.close()
                    st.toast(f"Perishability of {name} set to {new_p}")
                    st.rerun()

    bucket_ui("Cook today", plan["cook_today"])
    bucket_ui("Cook in 48 hours", plan["cook_48h"])
    bucket_ui("Freeze now", plan["freeze_now"])
    bucket_ui("Safe", plan["safe"])
