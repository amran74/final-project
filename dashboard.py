# dashboard.py — Analyst-grade dashboard for Smart Inventory
import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
from datetime import datetime, date, timedelta

from db import get_connection, get_monthly_summary  # reuse your DB connector

# --------------------------
# Helpers: Data extraction
# --------------------------
def _usage_df(user_id: int, days: int | None = 90) -> pd.DataFrame:
    conn = get_connection()
    c = conn.cursor()
    if days:
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        c.execute("""
            SELECT event_type, step_count, value_shekel, ts
            FROM usage_log
            WHERE user_id=? AND ts IS NOT NULL AND ts >= ?
            ORDER BY ts ASC
        """, (user_id, since))
    else:
        c.execute("""
            SELECT event_type, step_count, value_shekel, ts
            FROM usage_log
            WHERE user_id=? AND ts IS NOT NULL
            ORDER BY ts ASC
        """, (user_id,))
    rows = c.fetchall()
    conn.close()

    if not rows:
        return pd.DataFrame(columns=["event_type", "step_count", "value_shekel", "ts", "day"])

    df = pd.DataFrame(rows, columns=["event_type", "step_count", "value_shekel", "ts"])
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    df["day"] = df["ts"].dt.date
    df["step_count"] = pd.to_numeric(df["step_count"], errors="coerce").fillna(0).astype(int)
    df["value_shekel"] = pd.to_numeric(df["value_shekel"], errors="coerce").fillna(0.0)
    return df

def _inventory_df(user_id: int) -> pd.DataFrame:
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, name, type, amount, unit, expiration, price_per_unit, stable
        FROM inventory
        WHERE user_id=?
    """, (user_id,))
    rows = c.fetchall()
    conn.close()

    cols = ["id","name","type","amount","unit","expiration","price_per_unit","stable"]
    df = pd.DataFrame(rows, columns=cols)
    if df.empty:
        return df

    # clean/types
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
    df["price_per_unit"] = pd.to_numeric(df["price_per_unit"], errors="coerce").fillna(0.0)
    df["stable"] = df["stable"].fillna(0).astype(int)
    # dates
    today = date.today()
    def _days_left(x):
        try:
            return (date.fromisoformat(str(x)) - today).days
        except Exception:
            return np.nan
    df["days_to_exp"] = df["expiration"].apply(_days_left)
    df["value_at_risk"] = (df["amount"] * df["price_per_unit"]).round(2)
    return df

# --------------------------
# KPI calculations
# --------------------------
def _kpi_block(usage: pd.DataFrame, inv: pd.DataFrame, window_days: int):
    # time filter already applied in _usage_df
    used_steps = int(usage.loc[usage["event_type"]=="used", "step_count"].sum())
    exp_steps  = int(usage.loc[usage["event_type"]=="expired", "step_count"].sum())
    lost_nis   = float(usage.loc[usage["event_type"]=="expired", "value_shekel"].sum())
    total_items = int(len(inv))
    denom = used_steps + exp_steps
    waste_rate = (exp_steps/denom)*100 if denom > 0 else 0.0
    inv_value = float((inv["value_at_risk"]).sum()) if not inv.empty else 0.0
    avg_days_left = float(inv["days_to_exp"].dropna().mean()) if not inv.empty else np.nan
    return {
        "items": total_items,
        "used": used_steps,
        "expired": exp_steps,
        "lost": round(lost_nis, 2),
        "waste_rate": round(waste_rate, 1),
        "inv_value": round(inv_value, 2),
        "avg_days_left": None if np.isnan(avg_days_left) else round(avg_days_left, 1),
    }

def _previous_window_kpis(user_id: int, window_days: int):
    # used for deltas
    usage_prev = _usage_df(user_id, days=window_days*2)
    if usage_prev.empty:
        return {"used":0,"expired":0,"lost":0.0}
    cutoff = date.today() - timedelta(days=window_days)
    prev = usage_prev[usage_prev["day"] < cutoff]
    return {
        "used": int(prev.loc[prev["event_type"]=="used","step_count"].sum()),
        "expired": int(prev.loc[prev["event_type"]=="expired","step_count"].sum()),
        "lost": float(prev.loc[prev["event_type"]=="expired","value_shekel"].sum()),
    }

# --------------------------
# Charts
# --------------------------
def _trend_chart(usage: pd.DataFrame):
    if usage.empty:
        st.info("No usage data yet. Go touch some food.")
        return
    daily = usage.groupby(["day","event_type"]).agg(
        steps=("step_count","sum"),
        lost=("value_shekel","sum")
    ).reset_index()

    pivot = daily.pivot_table(index="day", columns="event_type", values="steps", fill_value=0).reset_index()
    pivot = pivot.rename(columns={"used":"Used", "expired":"Expired"})
    pivot_long = pivot.melt("day", var_name="Event", value_name="Steps")

    chart = alt.Chart(pivot_long).mark_line(point=True).encode(
        x=alt.X('day:T', title='Date'),
        y=alt.Y('Steps:Q'),
        color=alt.Color('Event:N', scale=alt.Scale(
            domain=["Used","Expired"],
            range=["#39c5bb","#ff6b6b"]
        )),
        tooltip=['day:T','Event:N','Steps:Q']
    ).properties(height=260)
    st.altair_chart(chart, use_container_width=True)

def _money_chart(usage: pd.DataFrame):
    cash = usage[usage["event_type"]=="expired"]
    if cash.empty:
        st.info("No money lost yet. Keep it that way.")
        return
    money = cash.groupby("day")["value_shekel"].sum().reset_index()
    bar = alt.Chart(money).mark_bar().encode(
        x=alt.X('day:T', title='Date'),
        y=alt.Y('value_shekel:Q', title='₪ lost'),
        tooltip=['day:T','value_shekel:Q']
    ).properties(height=200)
    st.altair_chart(bar, use_container_width=True)

def _pareto(inv: pd.DataFrame):
    if inv.empty:
        st.info("No items in stock.")
        return
    df = inv[["name","value_at_risk"]].copy()
    df = df.sort_values("value_at_risk", ascending=False)
    df["cum"] = df["value_at_risk"].cumsum()
    total = float(df["value_at_risk"].sum()) or 1.0
    df["cum_pct"] = df["cum"]/total * 100.0

    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X('name:N', sort=None, title='Items (sorted by value at risk)'),
        y=alt.Y('value_at_risk:Q', title='₪ at risk'),
        tooltip=['name:N','value_at_risk:Q','cum_pct:Q']
    )
    line = alt.Chart(df).mark_line(color='#ffd166').encode(
        x='name:N',
        y=alt.Y('cum_pct:Q', title='Cumulative %'),
    )
    rule = alt.Chart(pd.DataFrame({'y':[80]})).mark_rule(color='#ffd166', strokeDash=[6,4]).encode(y='y')
    chart = alt.layer(bars, line, rule).resolve_scale(y='independent').properties(height=280)
    st.altair_chart(chart, use_container_width=True)

def _risk_buckets(inv: pd.DataFrame):
    if inv.empty:
        st.info("No items to analyze.")
        return
    # Buckets by days to expiry
    bins = [-999, -1, 0, 3, 7, 14, 9999]
    labels = ["Expired","Today","0–3d","4–7d","8–14d",">14d"]
    df = inv.dropna(subset=["days_to_exp"]).copy()
    df["bucket"] = pd.cut(df["days_to_exp"], bins=bins, labels=labels, right=True)
    agg = df.groupby("bucket").size().reset_index(name="count")
    agg["bucket"] = pd.Categorical(agg["bucket"], categories=labels, ordered=True)
    agg = agg.sort_values("bucket")

    bar = alt.Chart(agg).mark_bar().encode(
        x=alt.X('bucket:N', title='Time to expire'),
        y=alt.Y('count:Q', title='Items'),
        color=alt.Color('bucket:N', legend=None,
                        scale=alt.Scale(domain=labels,
                                        range=["#7a7a7a","#ff9f1c","#ff6b6b","#ff948e","#ffd166","#39c5bb"])),
        tooltip=['bucket:N','count:Q']
    ).properties(height=200)
    st.altair_chart(bar, use_container_width=True)

# --------------------------
# Forecast (simple moving avg)
# --------------------------
def _forecast_expired(usage: pd.DataFrame, horizon_days=7):
    hist = usage[usage["event_type"]=="expired"].copy()
    if hist.empty:
        return 0, 0.0
    daily = hist.groupby("day").agg(
        steps=("step_count","sum"),
        money=("value_shekel","sum")
    ).reset_index().tail(28)  # last 4 weeks window
    mean_steps = daily["steps"].mean()
    mean_money = daily["money"].mean()
    return int(round(mean_steps * (horizon_days/1.0))), float(round(mean_money * (horizon_days/1.0), 2))

# --------------------------
# Dashboard page
# --------------------------
def dashboard():
    st.title("📊 Stats")

    if "user_id" not in st.session_state:
        st.warning("Please log in first.")
        return
    user_id = st.session_state["user_id"]

    # Controls
    colc1, colc2, colc3 = st.columns([2,2,1])
    with colc1:
        window = st.selectbox("Time window", ["Last 7 days","Last 30 days","Last 90 days","All time"], index=1)
    with colc2:
        show_downloads = st.checkbox("Enable CSV downloads", value=False)
    with colc3:
        st.write("")  # spacer

    days_map = {"Last 7 days":7,"Last 30 days":30,"Last 90 days":90,"All time":None}
    days = days_map[window]

    usage = _usage_df(user_id, days=days if days else None)
    inv = _inventory_df(user_id)

    # KPIs
    k = _kpi_block(usage, inv, window_days=days or 3650)
    prev = _previous_window_kpis(user_id, window_days=(days or 30))

    col1, col2, col3, col4, col5, col6 = st.columns(6)
    with col1:
        st.metric("Items in Stock", k["items"])
    with col2:
        delta_used = None if prev["used"]==0 else f"{((k['used']-prev['used'])/max(prev['used'],1))*100:.1f}%"
        st.metric("Used (steps)", k["used"], delta=delta_used)
    with col3:
        delta_exp = None if prev["expired"]==0 else f"{((k['expired']-prev['expired'])/max(prev['expired'],1))*100:.1f}%"
        st.metric("Expired (steps)", k["expired"], delta=delta_exp)
    with col4:
        delta_loss = None if prev["lost"]==0 else f"{((k['lost']-prev['lost'])/max(prev['lost'],1))*100:.1f}%"
        st.metric("Money lost", f"₪{k['lost']:.2f}", delta=delta_loss)
    with col5:
        st.metric("Waste rate", f"{k['waste_rate']:.1f}%")
    with col6:
        st.metric("Inv. value", f"₪{k['inv_value']:.2f}")

    st.divider()

    # Top row charts
    a, b = st.columns([3,2], gap="large")
    with a:
        st.subheader("Usage vs Expiry trend")
        _trend_chart(usage)
    with b:
        st.subheader("₪ Lost over time")
        _money_chart(usage)

    st.divider()

    # Risk + Pareto row
    r1, r2 = st.columns([2,3], gap="large")
    with r1:
        st.subheader("Expiry risk buckets")
        _risk_buckets(inv)
    with r2:
        st.subheader("Pareto: value-at-risk by item")
        _pareto(inv)

    st.divider()

    # Forecast + Hotlist
    f1, f2 = st.columns([2,3], gap="large")
    with f1:
        st.subheader("7-day waste forecast")
        steps_f, money_f = _forecast_expired(usage, horizon_days=7)
        st.write(f"Projected expired steps: **{steps_f}**")
        st.write(f"Projected money lost: **₪{money_f:.2f}**")
        if k["avg_days_left"] is not None:
            st.caption(f"Avg days left (all stock): {k['avg_days_left']}")

    with f2:
        st.subheader("Top items at risk (soonest expiration)")
        if inv.empty:
            st.info("No inventory.")
        else:
            today = date.today()
            hot = inv.copy()
            # rank by days_to_exp asc, then value risk desc
            hot = hot.sort_values(["days_to_exp","value_at_risk"], ascending=[True, False])
            hot = hot[["name","amount","unit","expiration","days_to_exp","value_at_risk","price_per_unit","type","stable"]]
            hot.rename(columns={
                "days_to_exp":"days_left",
                "value_at_risk":"₪_at_risk",
                "price_per_unit":"₪/unit",
                "stable":"pantry"
            }, inplace=True)
            st.dataframe(
                hot.head(12),
                use_container_width=True,
                hide_index=True
            )
            if show_downloads:
                csv = hot.to_csv(index=False).encode("utf-8")
                st.download_button("Download risk table (CSV)", csv, file_name="risk_items.csv", mime="text/csv")

    st.divider()

    # Inventory snapshot download
    if show_downloads and not inv.empty:
        inv_csv = inv.to_csv(index=False).encode("utf-8")
        st.download_button("Download inventory snapshot (CSV)", inv_csv, file_name="inventory_snapshot.csv", mime="text/csv")

    # Tiny footnote
    st.caption("Tip: Waste rate = expired steps / (used + expired). Pareto shows which items drive most value at risk.")
