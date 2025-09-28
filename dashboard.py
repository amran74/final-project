# dashboard.py
# Executive Dashboard with top-tab navigation, AI insights, and improved at-risk logic.
# Router-friendly: exposes dashboard() and app().

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Optional, Tuple

import pandas as pd
import streamlit as st
from db import get_connection
import sys as _sys

# Optional OpenAI import (graceful fallback)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# -----------------------------------------------------------------------------
# Router compatibility (some loaders import Dashboard, others dashboard)
# -----------------------------------------------------------------------------
_mod = _sys.modules.get(__name__)
if _mod is not None:
    _sys.modules.setdefault("Dashboard", _mod)
    _sys.modules.setdefault("dashboard", _mod)

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")

TODAY = date.today()

# -----------------------------------------------------------------------------
# Utilities
# -----------------------------------------------------------------------------
def _read_sql(sql: str, params: Tuple = ()) -> pd.DataFrame:
    con = get_connection()
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()

def _days_until(iso_str: Optional[str]) -> Optional[int]:
    if not iso_str:
        return None
    try:
        d = datetime.fromisoformat(iso_str).date()
        return (d - TODAY).days
    except Exception:
        return None

def _money(x: Optional[float]) -> str:
    try:
        return f"₪{float(x or 0):,.2f}"
    except Exception:
        return "₪0.00"

def _pretty_money(x: float) -> str:
    return f"₪{x:,.0f}" if x >= 1000 else f"₪{x:,.2f}"

def _step_for(base_unit: str) -> float:
    return 100.0 if (base_unit or "").lower() in ("g", "ml") else 1.0

def _friendly_qty(amount: float, unit: str) -> Tuple[float, str]:
    u = (unit or "pcs").lower()
    if u == "g":
        return (amount / 1000.0, "kg") if amount >= 1000 else (amount, "g")
    if u == "ml":
        return (amount / 1000.0, "l") if amount >= 1000 else (amount, "ml")
    return amount, (unit or "pcs")

def _likely_waste_value(on_hand_base: float,
                        days_until: Optional[int],
                        avg_daily_base: float,
                        price_per_base: float) -> float:
    # No expiry means we can't claim imminent waste due to date.
    if days_until is None or days_until < 0:
        return 0.0
    if avg_daily_base <= 0:
        return on_hand_base * max(price_per_base, 0.0)
    usable_before_expiry = avg_daily_base * max(days_until, 0)
    wasted_base = max(on_hand_base - usable_before_expiry, 0.0)
    return wasted_base * max(price_per_base, 0.0)

def _model_name() -> str:
    try:
        return st.secrets.get("RECIPE_AI_MODEL", "gpt-4o-mini")
    except Exception:
        return "gpt-4o-mini"

# -----------------------------------------------------------------------------
# Auth / user
# -----------------------------------------------------------------------------
def _resolve_user_id() -> Optional[int]:
    if "user_id" in st.session_state:
        return int(st.session_state["user_id"])

    st.warning("No active login. Pick a user to view data (read-only).")
    try:
        users = _read_sql("SELECT id, username FROM users ORDER BY username")
    except Exception:
        users = pd.DataFrame(columns=["id", "username"])

    if users.empty:
        st.info("No users found. Go to Login and create a user first.")
        return None

    pick = st.selectbox(
        "View as user",
        list(users.itertuples(index=False)),
        format_func=lambda r: f"{r.username} (id {r.id})",
        key="dash_viewas",
    )
    if st.button("View"):
        st.session_state["user_id"] = int(pick.id)
        st.session_state["view_only"] = True
        st.rerun()
    st.stop()

# -----------------------------------------------------------------------------
# Live data loaders (no caching)
# -----------------------------------------------------------------------------
def load_inventory_snapshot(user_id: int) -> pd.DataFrame:
    df = _read_sql(
        """
        SELECT id, name, type, base_unit,
               COALESCE(base_amount,0.0)    AS base_amount,
               COALESCE(price_per_base,0.0) AS price_per_base,
               COALESCE(total_cost,0.0)     AS total_cost,
               COALESCE(expiration,'')      AS expiration,
               COALESCE(stable,1)           AS stable
          FROM inventory
         WHERE user_id=?
        """,
        (user_id,),
    )
    df["value"] = df["base_amount"] * df["price_per_base"]
    df["days_until"] = df["expiration"].apply(_days_until)
    return df

def load_usage(user_id: int, since_iso: str) -> pd.DataFrame:
    return _read_sql(
        """
        SELECT u.item_id, u.event_type, COALESCE(u.step_count,0) AS step_count, u.ts,
               i.name, i.base_unit, COALESCE(i.price_per_base,0) AS price_per_base
          FROM usage_log u
          JOIN inventory i ON i.id = u.item_id
         WHERE u.user_id=? AND substr(u.ts,1,10)>=?
         ORDER BY u.ts DESC
        """,
        (user_id, since_iso),
    )

def load_purchases(user_id: int, month_prefix: Optional[str] = None) -> pd.DataFrame:
    if month_prefix:
        return _read_sql(
            """
            SELECT p.item_id, p.store_id, p.qty_base, p.unit_price_base, p.total_paid, p.ts,
                   i.name, i.type, i.base_unit, s.name AS store_name
              FROM purchases_log p
         LEFT JOIN inventory i ON i.id = p.item_id
         LEFT JOIN stores s    ON s.id = p.store_id
             WHERE p.user_id=? AND substr(p.ts,1,7)=?
             ORDER BY p.ts DESC
            """,
            (user_id, month_prefix),
        )
    return _read_sql(
        """
        SELECT p.item_id, p.store_id, p.qty_base, p.unit_price_base, p.total_paid, p.ts,
               i.name, i.type, i.base_unit, s.name AS store_name
          FROM purchases_log p
     LEFT JOIN inventory i ON i.id = p.item_id
     LEFT JOIN stores s    ON s.id = p.store_id
         WHERE p.user_id=?
         ORDER BY p.ts DESC
        """,
        (user_id,),
    )

def avg_daily_usage(df_usage: pd.DataFrame, since_iso: str) -> pd.DataFrame:
    if df_usage.empty:
        return pd.DataFrame(columns=["item_id", "avg_daily_base"])
    start = datetime.fromisoformat(since_iso).date()
    days = max(1, (TODAY - start).days)
    used = df_usage[df_usage["event_type"] == "used"].copy()
    if used.empty:
        return pd.DataFrame(columns=["item_id", "avg_daily_base"])

    def steps_to_amt(row):
        return float(row.step_count or 0.0) * _step_for(str(row.base_unit or "pcs"))

    used["amt_base"] = used.apply(steps_to_amt, axis=1)
    g = used.groupby("item_id", as_index=False)["amt_base"].sum()
    g["avg_daily_base"] = g["amt_base"] / days
    return g[["item_id", "avg_daily_base"]]

def coverage_days(inv: pd.DataFrame, avg_daily: pd.DataFrame) -> pd.DataFrame:
    if inv.empty:
        return inv.assign(coverage_days=math.inf)
    out = inv.merge(avg_daily, how="left", left_on="id", right_on="item_id")
    out["avg_daily_base"] = out["avg_daily_base"].fillna(0.0)
    out["coverage_days"] = out.apply(
        lambda r: (r["base_amount"] / r["avg_daily_base"]) if r["avg_daily_base"] > 0 else math.inf, axis=1
    )
    return out.drop(columns=["item_id"])

# -----------------------------------------------------------------------------
# AI helpers
# -----------------------------------------------------------------------------
def _ai_summary_payload(user_id: int, window_days: int = 60, month_pick: Optional[str] = None) -> dict:
    since_iso = (TODAY - timedelta(days=window_days)).strftime("%Y-%m-%d")
    inv = load_inventory_snapshot(user_id)
    usage = load_usage(user_id, since_iso)
    purch = load_purchases(user_id, month_pick or TODAY.strftime("%Y-%m"))

    inv_tiny = inv[["name", "type", "base_unit", "base_amount", "price_per_base", "value", "expiration"]].copy()
    inv_csv = inv_tiny.to_csv(index=False)

    expd = usage[usage["event_type"] == "expired"].copy()
    if not expd.empty:
        def expired_value(row):
            amt = float(row.step_count or 0.0) * _step_for(str(row.base_unit or "pcs"))
            return amt * float(row.price_per_base or 0.0)
        expd["waste_value"] = expd.apply(expired_value, axis=1)
        waste_tot = float(expd["waste_value"].sum())
        waste_top = (
            expd.groupby("name", as_index=False)["waste_value"]
            .sum()
            .sort_values("waste_value", ascending=False)
            .head(10)
            .values.tolist()
        )
    else:
        waste_tot = 0.0
        waste_top = []

    if purch.empty:
        spend_month = 0.0
        by_store = []
    else:
        spend_month = float(purch["total_paid"].sum())
        g = purch.groupby("store_name", as_index=False)["total_paid"].sum().sort_values("total_paid", ascending=False)
        by_store = g.values.tolist()

    meta = {
        "window_days": window_days,
        "since": since_iso,
        "month": month_pick or TODAY.strftime("%Y-%m"),
        "inventory_value": float(inv["value"].sum()),
        "items_on_hand": int((inv["base_amount"] > 0).sum()),
        "expiring_7_count": int(((inv["days_until"] >= 0) & (inv["days_until"] <= 7) & (inv["base_amount"] > 0)).sum()),
        "waste_total": waste_tot,
        "spend_month": spend_month,
    }
    return {"meta": meta, "inventory_csv": inv_csv, "waste_top": waste_top, "spend_by_store": by_store}

def _call_openai(prompt: str) -> Optional[str]:
    if OpenAI is None:
        return "OpenAI SDK missing. Install `openai>=1.0` and set OPENAI_API_KEY in Streamlit secrets."
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        return "OPENAI_API_KEY not found in Streamlit secrets."
    try:
        client = OpenAI(api_key=api_key)
        rsp = client.chat.completions.create(
            model=_model_name(),
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an operations analyst. Explain clearly for non-experts. "
                        "Use short sections, bullets, and concrete numbers. Give 3–6 specific actions."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        return rsp.choices[0].message.content.strip()
    except Exception as e:
        return f"OpenAI call failed: {e}"

# -----------------------------------------------------------------------------
# Tab screens
# -----------------------------------------------------------------------------
def tab_overview(user_id: int):
    c1, c2 = st.columns([1.2, 1.6])
    window_days = c1.slider("Analysis window (days)", 7, 180, 60, 1, key="ov_win")
    THIS_MONTH = TODAY.strftime("%Y-%m")
    PREV_MONTH = (TODAY - timedelta(days=31)).strftime("%Y-%m")
    month_pick = c2.selectbox("Spend month", [THIS_MONTH, PREV_MONTH], index=0, key="ov_month")

    since_iso = (TODAY - timedelta(days=window_days)).strftime("%Y-%m-%d")
    inv = load_inventory_snapshot(user_id)
    usage = load_usage(user_id, since_iso)
    purch_m = load_purchases(user_id, month_pick)

    total_value = inv["value"].sum()
    items_on_hand = int((inv["base_amount"] > 0).sum())
    expiring_7 = int(((inv["days_until"] >= 0) & (inv["days_until"] <= 7) & (inv["base_amount"] > 0)).sum())
    expired_events = int((usage["event_type"] == "expired").sum())
    used_events = int((usage["event_type"] == "used").sum())
    spent_month = float(purch_m["total_paid"].sum() if not purch_m.empty else 0.0)

    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Inventory value", _money(total_value))
    k2.metric("Items with stock", f"{items_on_hand}")
    k3.metric("Expiring ≤ 7 days", f"{expiring_7}")
    k4.metric("Expired events", f"{expired_events}")
    k5.metric("Used events", f"{used_events}")
    k6.metric(f"Spend {month_pick}", _money(spent_month))

    st.divider()
    left, right = st.columns([5, 2])

    with left:
        st.subheader("⏱️ Expiry timeline (next 60 days)")
        nxt = inv[(inv["expiration"] != "") & inv["expiration"].notna()].copy()
        if nxt.empty:
            st.caption("No expiries recorded.")
        else:
            nxt["exp_date"] = pd.to_datetime(nxt["expiration"], errors="coerce").dt.date
            end = TODAY + timedelta(days=60)
            nxt = nxt[(nxt["exp_date"] >= TODAY) & (nxt["exp_date"] <= end)]
            if nxt.empty:
                st.caption("Nothing expiring soon.")
            else:
                grp = nxt.groupby("exp_date", as_index=False).agg(items=("id", "count"), value=("value", "sum"))
                st.area_chart(grp.set_index("exp_date")[["items", "value"]])

        st.subheader("🧪 Waste (last window)")
        expd = usage[usage["event_type"] == "expired"].copy()
        if expd.empty:
            st.caption("No expired events.")
        else:
            def expired_value(row):
                amt = float(row.step_count or 0.0) * _step_for(str(row.base_unit or "pcs"))
                return amt * float(row.price_per_base or 0.0)

            expd["waste_value"] = expd.apply(expired_value, axis=1)
            top = (
                expd.groupby(["item_id", "name"], as_index=False)["waste_value"]
                .sum()
                .sort_values("waste_value", ascending=False)
                .head(10)
            )
            st.bar_chart(top.set_index("name")["waste_value"])

    with right:
        st.subheader("Guide")
        st.markdown(
            """
**Read this tab like a heartbeat monitor.**  
- Tiles query the DB every render.  
- “Expiring ≤ 7 days” counts only items with positive qty.  
- Waste ₪ = expired steps × step_size × ₪/base.
"""
        )

def tab_risk_waste(user_id: int):
    window_days = st.slider("Window (days)", 7, 120, 60, 1, key="rw_win")
    since_iso = (TODAY - timedelta(days=window_days)).strftime("%Y-%m-%d")
    inv = load_inventory_snapshot(user_id)
    usage = load_usage(user_id, since_iso)

    left, right = st.columns([5, 2])

    with left:
        st.subheader("Critical & Upcoming Expiry")
        nxt = inv[(inv["expiration"] != "") & inv["expiration"].notna()].copy()
        nxt["exp_date"] = pd.to_datetime(nxt["expiration"], errors="coerce").dt.date
        crit = nxt[nxt["exp_date"] <= TODAY]
        soon = nxt[(nxt["exp_date"] > TODAY) & (nxt["exp_date"] <= TODAY + timedelta(days=7))]
        c1, c2 = st.columns(2)
        c1.metric("Already expired", int(len(crit)))
        c2.metric("Expire ≤ 7 days", int(len(soon)))

        if not soon.empty:
            grp = soon.groupby("exp_date", as_index=False).agg(items=("id", "count"), value=("value", "sum"))
            st.area_chart(grp.set_index("exp_date")[["items", "value"]])

        st.subheader("Top Waste Culprits")
        expd = usage[usage["event_type"] == "expired"].copy()
        if expd.empty:
            st.caption("No expired events in window.")
        else:
            def expired_value(row):
                amt = float(row.step_count or 0.0) * _step_for(str(row.base_unit or "pcs"))
                return amt * float(row.price_per_base or 0.0)

            expd["waste_value"] = expd.apply(expired_value, axis=1)
            top = (
                expd.groupby(["item_id", "name"], as_index=False)["waste_value"]
                .sum()
                .sort_values("waste_value", ascending=False)
            )
            top["₪ waste"] = top["waste_value"].apply(_money)
            st.bar_chart(top.head(15).set_index("name")["waste_value"])
            with st.expander("Details"):
                st.dataframe(top[["name", "₪ waste"]], use_container_width=True)

    with right:
        st.subheader("Guide")
        st.markdown(
            """
**Ops triage.**  
- Hit “soon” list first; use/freeze now.  
- Waste table shows where rules or par levels matter most.  
- Then use SmartCoach to automate routine saves.
"""
        )

def tab_spend_suppliers(user_id: int):
    THIS_MONTH = TODAY.strftime("%Y-%m")
    PREV_MONTH = (TODAY - timedelta(days=31)).strftime("%Y-%m")
    month_pick = st.selectbox("Month", [THIS_MONTH, PREV_MONTH], index=0, key="ss_month")
    purch = load_purchases(user_id, month_pick)

    left, right = st.columns([5, 2])

    with left:
        st.subheader(f"Spend by store ({month_pick})")
        if purch.empty:
            st.caption("No purchases for selected month.")
        else:
            g = purch.copy()
            g["store_name"] = g["store_name"].fillna("Unknown")
            g = g.groupby("store_name", as_index=False)["total_paid"].sum().sort_values("total_paid", ascending=False)
            st.bar_chart(g.set_index("store_name")["total_paid"])
            with st.expander("Table"):
                g["₪"] = g["total_paid"].apply(_money)
                st.dataframe(g[["store_name", "₪"]], use_container_width=True)

        st.subheader("ABC (Pareto) by spend (last 90 days)")
        p_all = load_purchases(user_id)
        if p_all.empty:
            st.caption("No purchase history.")
        else:
            p = p_all[p_all["ts"] >= (TODAY - timedelta(days=90)).strftime("%Y-%m-%d")].copy()
            g = p.groupby(["item_id", "name"], as_index=False)["total_paid"].sum().sort_values("total_paid", ascending=False)
            if g.empty:
                st.caption("Nothing in last 90 days.")
            else:
                g["cum_share"] = g["total_paid"].cumsum() / g["total_paid"].sum()
                g["Class"] = g["cum_share"].apply(lambda x: "A" if x <= 0.80 else "B" if x <= 0.95 else "C")
                counts = g["Class"].value_counts().reindex(["A", "B", "C"]).fillna(0).astype(int)
                st.bar_chart(counts)
                with st.expander("Top A items"):
                    topA = g[g["Class"] == "A"].copy()
                    topA["₪"] = topA["total_paid"].apply(_money)
                    st.dataframe(topA[["name", "₪", "cum_share"]], use_container_width=True)

    with right:
        st.subheader("Guide")
        st.markdown(
            """
**Procurement view.**  
- Stores bar shows who gets your money.  
- ABC: negotiate A, standardize B, ignore C.
"""
        )

def tab_coverage_forecast(user_id: int):
    # Improved at-risk logic: likely waste and sensible ordering
    window_days = st.slider("Usage window (days)", 7, 180, 60, 1, key="cf_win")
    since_iso = (TODAY - timedelta(days=window_days)).strftime("%Y-%m-%d")

    inv = load_inventory_snapshot(user_id)
    usage = load_usage(user_id, since_iso)
    avg = avg_daily_usage(usage, since_iso)
    cov = coverage_days(inv, avg)  # includes avg_daily_base already; do NOT re-merge

    if cov.empty:
        st.caption("No inventory.")
        return

    # Safety: ensure column exists
    if "avg_daily_base" not in cov.columns:
        cov["avg_daily_base"] = 0.0

    cov["likely_waste"] = cov.apply(
        lambda r: _likely_waste_value(
            float(r.get("base_amount", 0.0)),
            int(r["days_until"]) if pd.notnull(r["days_until"]) else None,
            float(r.get("avg_daily_base", 0.0)),
            float(r.get("price_per_base", 0.0)),
        ),
        axis=1,
    )

    # Display rows that actually represent risk
    show = cov[
        ((cov["days_until"].notna()) & (cov["days_until"] <= 14))  # expiring soon
        | (cov["likely_waste"] > 0.0)                              # won't finish before date
        | (cov["coverage_days"] < 7)                               # low stock even without date
    ].copy()

    if show.empty:
        st.caption("No material risk detected in the chosen window.")
    else:
        records = []
        for _, r in show.iterrows():
            qty, unit = _friendly_qty(float(r.get("base_amount", 0.0)), str(r.get("base_unit", "pcs")))
            records.append({
                "Item": r.get("name", ""),
                "Type": r.get("type", ""),
                "On hand": f"{qty:,.0f} {unit}" if unit in ("pcs", "kg", "l") else f"{qty:,.1f} {unit}",
                "₪/base": f"{float(r.get('price_per_base', 0.0)):.4f}",
                "Value ₪": _pretty_money(float(r.get("value", 0.0))),
                "Days left": (int(r["days_until"]) if pd.notnull(r["days_until"]) else None),
                "Coverage (d)": ("∞" if math.isinf(float(r.get("coverage_days", math.inf))) else f"{float(r.get('coverage_days', 0.0)):.1f}"),
                "Likely waste ₪": _pretty_money(float(r.get("likely_waste", 0.0))),
            })

        df = pd.DataFrame(records)
        # Sort earliest expiry first, then most likely waste; None days at bottom
        df = df.sort_values(by=["Days left", "Likely waste ₪"], ascending=[True, False], na_position="last")

        st.subheader("At-risk: expiry vs usage capacity")
        st.dataframe(df, use_container_width=True, height=460)

    with st.expander("How to read this"):
        st.markdown(
            """
- **Likely waste ₪** estimates what you won’t finish before expiry at your recent usage rate.  
- **Coverage (d)** is a hint; when **Days left** is small, expiry wins.  
- Work top to bottom, then add par levels or SmartCoach rules for repeat offenders.
"""
        )

def tab_trends(user_id: int):
    left, right = st.columns([5, 2])
    with left:
        pu_all = load_purchases(user_id)
        if pu_all.empty:
            st.caption("No purchases recorded.")
            return
        items = pu_all[["item_id", "name"]].dropna().drop_duplicates().sort_values("name")
        if items.empty:
            st.caption("No named items found.")
            return
        pick = st.selectbox("Item", list(items.itertuples(index=False)), format_func=lambda r: r.name, key="trend_pick")
        trend = pu_all[pu_all["item_id"] == pick.item_id].copy()
        if len(trend) < 2:
            st.caption("Need at least two purchases to show a trend.")
            return
        trend["ts_date"] = pd.to_datetime(trend["ts"], errors="coerce")
        trend = trend.sort_values("ts_date")
        st.line_chart(trend.set_index("ts_date")[["unit_price_base"]])
        with st.expander("Table"):
            t = trend[["ts", "store_name", "qty_base", "unit_price_base", "total_paid"]].copy()
            t.rename(
                columns={
                    "ts": "Date",
                    "store_name": "Store",
                    "qty_base": "Qty (base)",
                    "unit_price_base": "₪/base",
                    "total_paid": "Paid ₪",
                },
                inplace=True,
            )
            t["Paid ₪"] = t["Paid ₪"].apply(_money)
            st.dataframe(t, use_container_width=True)
    with right:
        st.subheader("Guide")
        st.markdown(
            """
**Pricing telemetry.**  
- Watch slope; shift stores if it rises.  
- Lock contracts on chronic risers.
"""
        )

def tab_ai_insights(user_id: int):
    left, right = st.columns([5, 2])

    with left:
        window_days = st.slider("Analysis window (days)", 30, 180, 60, 10, key="ai_win")
        THIS_MONTH = TODAY.strftime("%Y-%m")
        PREV_MONTH = (TODAY - timedelta(days=31)).strftime("%Y-%m")
        month_pick = st.selectbox("Spend month", [THIS_MONTH, PREV_MONTH], index=0, key="ai_month")

        payload = _ai_summary_payload(user_id, window_days, month_pick)

        st.subheader("Executive summary")
        with st.spinner("Asking AI to read your data..."):
            prompt = (
                "Read this data and produce a short executive summary in plain language, then give concrete actions.\n\n"
                f"META: {payload['meta']}\n\n"
                f"WASTE_TOP (name,₪): {payload['waste_top']}\n\n"
                f"SPEND_BY_STORE (store,₪): {payload['spend_by_store']}\n\n"
                "INVENTORY_CSV:\n"
                f"{payload['inventory_csv'][:20000]}"
            )
            ans = _call_openai(prompt)
        st.markdown(ans or "No response.")

        st.divider()
        st.subheader("Ask a question about the data")
        q = st.text_input("Question (e.g., What should I buy less of next month?)", key="ai_q")
        if q:
            with st.spinner("Thinking..."):
                prompt_q = (
                    "Answer the question using only the following data. If uncertain, say what else is needed.\n\n"
                    f"QUESTION: {q}\n\nMETA: {payload['meta']}\n\n"
                    f"WASTE_TOP: {payload['waste_top']}\n\nSPEND_BY_STORE: {payload['spend_by_store']}\n\n"
                    f"INVENTORY_CSV:\n{payload['inventory_csv'][:20000]}"
                )
                ans_q = _call_openai(prompt_q)
            st.markdown(ans_q or "No response.")

    with right:
        st.subheader("Guide")
        st.markdown(
            """
**AI analyst.**  
- Feeds a compact snapshot into the model each time.  
- Keep purchases/usage updated or the AI is reading fiction.
"""
        )

def tab_raw(user_id: int):
    window_days = st.slider("Usage window (days)", 7, 180, 60, 1, key="raw_win")
    since_iso = (TODAY - timedelta(days=window_days)).strftime("%Y-%m-%d")
    THIS_MONTH = TODAY.strftime("%Y-%m")

    inv = load_inventory_snapshot(user_id)
    usage = load_usage(user_id, since_iso)
    purch_m = load_purchases(user_id, THIS_MONTH)

    left, right = st.columns([5, 2])

    with left:
        st.subheader("Inventory snapshot")
        if inv.empty:
            st.caption("No inventory.")
        else:
            snap = inv[
                ["name", "type", "base_unit", "base_amount", "price_per_base", "value", "expiration", "days_until"]
            ].copy()
            snap.rename(
                columns={
                    "name": "Item",
                    "type": "Type",
                    "base_unit": "Unit",
                    "base_amount": "On hand",
                    "price_per_base": "₪/base",
                    "value": "Value ₪",
                    "expiration": "Expiry",
                    "days_until": "Days left",
                },
                inplace=True,
            )
            snap["Value ₪"] = snap["Value ₪"].apply(_money)
            st.dataframe(
                snap.sort_values(["Days left", "Value ₪"], na_position="last"),
                use_container_width=True,
                height=350,
            )

        st.subheader("Usage log")
        if usage.empty:
            st.caption(f"No usage entries since {since_iso}.")
        else:
            u = usage.rename(
                columns={
                    "ts": "Date",
                    "name": "Item",
                    "base_unit": "Unit",
                    "event_type": "Event",
                    "step_count": "Steps",
                    "price_per_base": "₪/base",
                }
            )
            st.dataframe(u[["Date", "Event", "Item", "Unit", "Steps", "₪/base"]], use_container_width=True, height=300)

        st.subheader("Purchases")
        if purch_m.empty:
            st.caption(f"No purchases for {THIS_MONTH}.")
        else:
            p = purch_m.rename(
                columns={
                    "ts": "Date",
                    "store_name": "Store",
                    "name": "Item",
                    "qty_base": "Qty (base)",
                    "unit_price_base": "₪/base",
                    "total_paid": "Paid ₪",
                    "type": "Type",
                    "base_unit": "Unit",
                }
            )
            p["Paid ₪"] = p["Paid ₪"].apply(_money)
            st.dataframe(
                p[["Date", "Store", "Item", "Type", "Unit", "Qty (base)", "₪/base", "Paid ₪"]],
                use_container_width=True,
                height=300,
            )

# -----------------------------------------------------------------------------
# Main (tabs like Recipes)
# -----------------------------------------------------------------------------
def main():
    st.title("📊 Dashboard")
    user_id = _resolve_user_id()

    tabs = st.tabs(
        ["Overview", "Risk & Waste", "Spend & Suppliers", "Coverage & Forecast", "Trends", "AI Insights", "Raw Data"]
    )

    with tabs[0]:
        tab_overview(user_id)
    with tabs[1]:
        tab_risk_waste(user_id)
    with tabs[2]:
        tab_spend_suppliers(user_id)
    with tabs[3]:
        tab_coverage_forecast(user_id)
    with tabs[4]:
        tab_trends(user_id)
    with tabs[5]:
        tab_ai_insights(user_id)
    with tabs[6]:
        tab_raw(user_id)

# Router entry points your loader expects
def dashboard():
    main()

def app():
    main()

app = dashboard

if __name__ == "__main__":
    main()
