# dashboard.py — Executive BI Dashboard (Crown Jewel, no deadweight)
# Polished, interactive, and fast. Tabs, drill-downs, forecasting, simulator, exports.

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Tuple, Dict, Any

import numpy as np
import pandas as pd
import altair as alt
import streamlit as st

from db import get_connection, get_monthly_summary

# ------------------------------------------------------------------------------
# Page config
# ------------------------------------------------------------------------------
st.set_page_config(page_title="📊 Executive Dashboard", page_icon="📊", layout="wide")

PRIMARY_OK = "#14b8a6"   # teal (used/good)
PRIMARY_BAD = "#ef4444"  # red (expired/bad)
PRIMARY_WARN = "#f59e0b" # amber (risk/warn)

# ------------------------------------------------------------------------------
# Caching & Data Access
# ------------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load_history(user_id: int) -> pd.DataFrame:
    """
    usage_log JOIN inventory -> tidy dataframe
    Columns: ts, month, event_type, step_count, name, type, price_per_base, value
    """
    conn = get_connection()
    q = """
      SELECT u.ts, u.event_type, u.step_count, i.name, i.type, COALESCE(i.price_per_base, 0.0) AS price_per_base
        FROM usage_log u
        JOIN inventory i ON i.id = u.item_id
       WHERE u.user_id=?
    """
    df = pd.read_sql_query(q, conn, params=(user_id,))
    conn.close()
    if df.empty:
        return df
    # Normalize
    df["ts"] = pd.to_datetime(df["ts"], errors="coerce").fillna(pd.Timestamp.utcnow())
    df["month"] = df["ts"].dt.to_period("M").dt.to_timestamp()
    df["event_type"] = df["event_type"].str.lower().str.strip()
    df["step_count"] = pd.to_numeric(df["step_count"], errors="coerce").fillna(0).astype(float)
    df["value"] = df["step_count"] * pd.to_numeric(df["price_per_base"], errors="coerce").fillna(0.0)
    return df

@st.cache_data(show_spinner=False)
def _kpis(user_id: int) -> Tuple[int, int, int, float]:
    conn = get_connection(); c = conn.cursor()
    try:
        c.execute("SELECT COUNT(*) FROM inventory WHERE user_id=?", (user_id,))
        total_items = int(c.fetchone()[0] or 0)
    finally:
        conn.close()
    ms = get_monthly_summary(user_id)
    used = int(ms.get("used_steps", 0))
    expired = int(ms.get("expired_steps", 0))
    lost = float(ms.get("money_lost", 0.0))
    return total_items, used, expired, lost

@st.cache_data(show_spinner=False)
def _categories_for_user(user_id: int) -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("SELECT DISTINCT COALESCE(type,'Other') AS type FROM inventory WHERE user_id=?", conn, params=(user_id,))
    conn.close()
    return df

# ------------------------------------------------------------------------------
# Analytics helpers
# ------------------------------------------------------------------------------
def _month_deltas(hist: pd.DataFrame) -> Tuple[int, int]:
    if hist.empty:
        return 0, 0
    # current month
    cm = pd.Timestamp(date.today().replace(day=1))
    lm = (cm - pd.DateOffset(months=1)).to_period("M").to_timestamp()
    cur = hist[hist["month"] == cm]
    last = hist[hist["month"] == lm]
    used_delta = int(cur[cur["event_type"] == "used"]["step_count"].sum() - last[last["event_type"] == "used"]["step_count"].sum())
    exp_delta = int(cur[cur["event_type"] == "expired"]["step_count"].sum() - last[last["event_type"] == "expired"]["step_count"].sum())
    return used_delta, exp_delta

def _insights(used_this: int, expired_this: int, lost_this: float, used_delta: int, exp_delta: int, hist: pd.DataFrame) -> Dict[str, Any]:
    lines = []
    if exp_delta > 0:
        lines.append(f"Waste increased by {exp_delta} vs last month.")
    elif exp_delta < 0:
        lines.append(f"Waste decreased by {abs(exp_delta)} vs last month.")
    if used_delta > 0:
        lines.append(f"Usage improved by {used_delta} vs last month.")
    elif used_delta < 0:
        lines.append(f"Usage fell by {abs(used_delta)} vs last month.")
    if lost_this > 0:
        lines.append(f"Money lost this month: ₪{lost_this:.2f}.")
    if used_this >= expired_this:
        lines.append("You used more than you wasted this month.")
    # Worst category this month by money
    if not hist.empty:
        cm = pd.Timestamp(date.today().replace(day=1))
        cm_df = hist[(hist["month"] == cm) & (hist["event_type"] == "expired")]
        if not cm_df.empty:
            by_cat = cm_df.groupby("type")["value"].sum().sort_values(ascending=False)
            top_cat, top_val = by_cat.index[0], float(by_cat.iloc[0])
            lines.append(f"Highest waste category: {top_cat} (₪{top_val:.2f}).")
    if not lines:
        lines.append("No notable changes detected.")
    return {"bullets": lines}

def _forecast_next_month(hist: pd.DataFrame) -> Tuple[float, float]:
    """
    Simple linear regression over monthly expired value to forecast next month.
    Returns (yhat, r2). Requires >= 3 points.
    """
    if hist.empty:
        return 0.0, 0.0
    monthly = hist[hist["event_type"] == "expired"].groupby("month")["value"].sum().reset_index()
    if len(monthly) < 3:
        return float(monthly["value"].iloc[-1] if len(monthly) else 0.0), 0.0
    monthly = monthly.sort_values("month")
    x = np.arange(len(monthly), dtype=float)
    y = monthly["value"].to_numpy(dtype=float)
    # Linear regression
    A = np.vstack([x, np.ones_like(x)]).T
    coef, resid, _, _ = np.linalg.lstsq(A, y, rcond=None)
    m, b = coef
    yhat_next = m * (len(monthly)) + b
    # R^2
    yhat = m * x + b
    ss_res = np.sum((y - yhat) ** 2)
    ss_tot = np.sum((y - np.mean(y)) ** 2) or 1.0
    r2 = 1 - ss_res / ss_tot
    return max(0.0, float(yhat_next)), float(r2)

# ------------------------------------------------------------------------------
# Charts
# ------------------------------------------------------------------------------
def _trend_chart(trend_df: pd.DataFrame) -> alt.Chart:
    base = alt.Chart(trend_df).encode(
        x=alt.X("month:T", title=None),
        y=alt.Y("step_count:Q", title="Units"),
        color=alt.Color("event_type:N", scale=alt.Scale(domain=["used", "expired"], range=[PRIMARY_OK, PRIMARY_BAD])),
        tooltip=["month:T", "event_type:N", alt.Tooltip("step_count:Q", title="Units"), alt.Tooltip("value:Q", title="Value")]
    )
    return (base.mark_line(point=True)).properties(height=320)

def _category_chart(cat_df: pd.DataFrame) -> alt.Chart:
    return alt.Chart(cat_df).mark_bar().encode(
        y=alt.Y("type:N", sort="-x", title=None),
        x=alt.X("step_count:Q", title="Units"),
        color=alt.Color("event_type:N", scale=alt.Scale(domain=["used", "expired"], range=[PRIMARY_OK, PRIMARY_BAD])),
        tooltip=["type:N", "event_type:N", alt.Tooltip("step_count:Q", title="Units"), alt.Tooltip("value:Q", title="Value")]
    ).properties(height=360)

def _pareto_chart(pareto_df: pd.DataFrame, top_n: int = 30) -> alt.Chart:
    data = pareto_df.head(top_n)
    bars = alt.Chart(data).mark_bar().encode(
        x=alt.X("name:N", sort="-y", title=None),
        y=alt.Y("value:Q", title="Waste (₪)"),
        tooltip=["name:N", alt.Tooltip("value:Q", title="Waste (₪)")]
    ).properties(height=280)
    line = alt.Chart(data).mark_line(color=PRIMARY_WARN).encode(
        x="name:N",
        y=alt.Y("cumshare:Q", axis=alt.Axis(format='%'), title="Cumulative share"),
    )
    return alt.layer(bars, line).resolve_scale(y='independent')

# ------------------------------------------------------------------------------
# Tabs Rendering
# ------------------------------------------------------------------------------
def _tab_overview(user_id: int, hist: pd.DataFrame):
    total_items, used, expired, lost = _kpis(user_id)
    used_delta, exp_delta = _month_deltas(hist)

    st.subheader("Overview")

    # KPI row
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📦 Items tracked", total_items)
    c2.metric("✅ Used (month)", used, delta=used_delta)
    c3.metric("⛔ Expired (month)", expired, delta=exp_delta)
    c4.metric("💸 Money lost (month)", f"₪{lost:.2f}")
    c5.metric("💡 Savings potential (20%)", f"₪{lost*0.20:.2f}")

    st.markdown("---")

    # Insights
    insights = _insights(used, expired, lost, used_delta, exp_delta, hist)
    st.subheader("Key insights")
    for bullet in insights["bullets"]:
        st.write(f"• {bullet}")

def _tab_trends(hist: pd.DataFrame):
    st.subheader("Trends")

    # Filters
    min_d, max_d = hist["ts"].min().date(), hist["ts"].max().date()
    col_a, col_b = st.columns([2, 3])
    with col_a:
        start, end = st.date_input("Date range", (min_d, max_d), min_value=min_d, max_value=max_d)
    with col_b:
        ev = st.multiselect("Event type", ["used", "expired"], default=["used", "expired"])

    mask = (hist["ts"].dt.date >= start) & (hist["ts"].dt.date <= end) & (hist["event_type"].isin(ev))
    f = hist.loc[mask].copy()

    trend = f.groupby(["month", "event_type"]).agg(step_count=("step_count", "sum"), value=("value", "sum")).reset_index()
    st.altair_chart(_trend_chart(trend), use_container_width=True)

    # Drill-down table for the selected period
    with st.expander("Details (filtered period)"):
        day_summary = f.groupby([f["ts"].dt.date.rename("day"), "event_type"]).agg(
            units=("step_count", "sum"), value=("value", "sum")
        ).reset_index().sort_values(["day", "event_type"])
        st.dataframe(day_summary, use_container_width=True)

def _tab_categories(hist: pd.DataFrame):
    st.subheader("Categories")

    cat = hist.groupby(["type", "event_type"]).agg(step_count=("step_count", "sum"), value=("value", "sum")).reset_index()
    st.altair_chart(_category_chart(cat), use_container_width=True)

    # Drill-down by category
    categories = sorted(cat["type"].unique().tolist())
    sel = st.selectbox("Drill-down category", categories)
    drill = hist[hist["type"] == sel].copy()
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**Top used in {sel}**")
        used_items = drill[drill["event_type"] == "used"].groupby("name").agg(units=("step_count", "sum")).reset_index()
        st.dataframe(used_items.sort_values("units", ascending=False).head(10), use_container_width=True)
    with col2:
        st.markdown(f"**Top wasted in {sel}**")
        expired_items = drill[drill["event_type"] == "expired"].groupby("name").agg(
            units=("step_count", "sum"), value=("value", "sum")
        ).reset_index()
        st.dataframe(expired_items.sort_values(["value", "units"], ascending=[False, False]).head(10), use_container_width=True)

def _tab_pareto(hist: pd.DataFrame):
    st.subheader("Pareto (80/20)")

    waste = hist[hist["event_type"] == "expired"].groupby("name").agg(value=("value", "sum")).reset_index()
    if waste.empty:
        st.info("No waste recorded.")
        return
    waste = waste.sort_values("value", ascending=False)
    waste["cumshare"] = waste["value"].cumsum() / waste["value"].sum()

    st.altair_chart(_pareto_chart(waste, top_n=30), use_container_width=True)

    with st.expander("Top drivers table"):
        st.dataframe(waste.head(50), use_container_width=True)

    # Item detail drilldown
    items = waste["name"].tolist()
    chosen = st.selectbox("Inspect item history", items[:50])
    d = hist[hist["name"] == chosen].copy()
    if d.empty:
        st.write("No history.")
        return
    # Monthly line for this item
    line_df = d.groupby(["month", "event_type"]).agg(units=("step_count", "sum"), value=("value", "sum")).reset_index()
    chart = alt.Chart(line_df).mark_line(point=True).encode(
        x="month:T",
        y="units:Q",
        color=alt.Color("event_type:N", scale=alt.Scale(domain=["used", "expired"], range=[PRIMARY_OK, PRIMARY_BAD])),
        tooltip=["month:T", "event_type:N", "units:Q", "value:Q"],
    ).properties(height=280)
    st.altair_chart(chart, use_container_width=True)

def _tab_forecast(hist: pd.DataFrame):
    st.subheader("Forecast (next month)")

    monthly = hist.groupby(["month", "event_type"]).agg(value=("value", "sum")).reset_index()
    base = monthly[monthly["event_type"] == "expired"].copy()
    base = base.sort_values("month")
    if base.empty:
        st.info("Not enough data to forecast.")
        return

    yhat, r2 = _forecast_next_month(hist)
    cm = pd.Timestamp(date.today().replace(day=1))
    next_m = (cm + pd.DateOffset(months=1)).to_period("M").to_timestamp()

    # Chart historical + forecast point
    base["label"] = "History"
    forecast_df = pd.DataFrame({"month": [next_m], "value": [max(0.0, yhat)], "label": ["Forecast"]})
    plot_df = pd.concat([base[["month", "value", "label"]], forecast_df], ignore_index=True)

    chart = alt.Chart(plot_df).mark_line(point=True).encode(
        x="month:T",
        y=alt.Y("value:Q", title="Waste (₪)"),
        color=alt.Color("label:N", scale=alt.Scale(domain=["History", "Forecast"], range=[PRIMARY_BAD, PRIMARY_WARN])),
        tooltip=["month:T", "label:N", alt.Tooltip("value:Q", title="Waste (₪)")]
    ).properties(height=320)
    st.altair_chart(chart, use_container_width=True)

    st.caption(f"Forecast R² (fit quality): {r2:.2f} — simple linear model.")

def _tab_simulator(lost_month: float):
    st.subheader("Savings Simulator")
    percent = st.slider("Reduce waste by (%)", 0, 100, 20, step=5)
    monthly_save = lost_month * (percent / 100)
    yearly_save = monthly_save * 12
    c1, c2, c3 = st.columns(3)
    c1.metric("Monthly savings", f"₪{monthly_save:.2f}")
    c2.metric("Yearly savings", f"₪{yearly_save:.2f}")
    c3.metric("Assumed current loss (mo)", f"₪{lost_month:.2f}")

def _tab_data(hist: pd.DataFrame):
    st.subheader("Data")
    with st.expander("Usage history (raw)"):
        st.dataframe(hist.sort_values("ts", ascending=False), use_container_width=True, height=380)
    st.download_button(
        "📥 Download history CSV",
        data=hist.to_csv(index=False).encode("utf-8"),
        file_name="usage_history.csv",
        mime="text/csv"
    )

# ------------------------------------------------------------------------------
# Entry
# ------------------------------------------------------------------------------
def dashboard():
    st.title("📊 Executive Dashboard")
    st.caption(f"As of {date.today():%A, %d %B %Y}")

    if "user_id" not in st.session_state:
        st.warning("Please login first.")
        st.stop()
    user_id = int(st.session_state["user_id"])

    hist = _load_history(user_id)
    total_items, used, expired, lost = _kpis(user_id)

    # Tabs
    tabs = st.tabs(["Overview", "Trends", "Categories", "Pareto", "Forecast", "Simulator", "Data"])
    with tabs[0]:
        _tab_overview(user_id, hist)
    with tabs[1]:
        if hist.empty: st.info("No history yet."); 
        else: _tab_trends(hist)
    with tabs[2]:
        if hist.empty: st.info("No history yet."); 
        else: _tab_categories(hist)
    with tabs[3]:
        if hist.empty: st.info("No history yet."); 
        else: _tab_pareto(hist)
    with tabs[4]:
        if hist.empty: st.info("Not enough data to forecast."); 
        else: _tab_forecast(hist)
    with tabs[5]:
        _tab_simulator(lost)
    with tabs[6]:
        _tab_data(hist)

def app():
    dashboard()

if __name__ == "__main__":
    dashboard()
