# dashboard.py — BI-polished, tabbed dashboard wired to dashboards_core
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional, Tuple

import altair as alt
import pandas as pd
import streamlit as st

from db import get_connection
from dashboards_core import (
    TODAY,
    kpis_for_window,
    waste_and_spend_series,
    top_waste_items,
    category_split,
    store_waste,
    daily_heatmap,
    waste_events,
    expiring_soon,
    sanity_report,
)

# Optional OpenAI import (graceful fallback)
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

# --------------------------------------------------------------------------------------
# Page config
# --------------------------------------------------------------------------------------

st.set_page_config(page_title="Dashboard", page_icon="📊", layout="wide")

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------

def _read_sql(sql: str, params=()) -> pd.DataFrame:
    con = get_connection()
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()


def _resolve_user_id() -> Optional[int]:
    if "user_id" in st.session_state:
        return int(st.session_state["user_id"])
    try:
        users = _read_sql("SELECT id, username FROM users ORDER BY username")
    except Exception:
        users = pd.DataFrame(columns=["id", "username"])
    if users.empty:
        st.error("No users. Create a user first.")
        return None
    pick = st.selectbox(
        "View as user",
        list(users.itertuples(index=False)),
        format_func=lambda r: f"{r.username} (id {r.id})",
        key="viewas",
    )
    if st.button("Load", use_container_width=False):
        st.session_state["user_id"] = int(pick.id)
        st.rerun()
    st.stop()


def _window_selector(default_days: int = 30, key: str = "win") -> Tuple[date, date, str]:
    c1, c2 = st.columns([1, 2])
    days = c1.select_slider(
        "Window",
        options=[7, 14, 30, 60, 90],
        value=default_days,
        key=f"{key}_days",
    )
    bucket = c2.radio(
        "Trend bucket",
        ["Day", "Week", "Month"],
        horizontal=True,
        index=0,
        key=f"{key}_bucket",
    )
    start = TODAY - timedelta(days=days)
    end = TODAY
    return start, end, bucket


# Window-scoped purchase loaders for richer supplier/cost pages

def _load_purchases_window(user_id: int, start: date, end: date) -> pd.DataFrame:
    sql = (
        """
        SELECT p.item_id, p.store_id, COALESCE(p.qty_base,0) AS qty_base,
               COALESCE(p.unit_price_base,0) AS unit_price_base,
               COALESCE(p.total_paid,0) AS total_paid,
               p.ts,
               i.name AS item_name, i.type AS item_type, i.base_unit,
               COALESCE(s.name,'Unknown') AS store_name
          FROM purchases_log p
          LEFT JOIN inventory i ON i.id = p.item_id
          LEFT JOIN stores s    ON s.id = p.store_id
         WHERE p.user_id=? AND substr(p.ts,1,10) BETWEEN ? AND ?
        """
    )
    return _read_sql(sql, (user_id, str(start), str(end)))


def _load_purchases_days(user_id: int, days: int = 90) -> pd.DataFrame:
    start = TODAY - timedelta(days=days)
    end = TODAY
    return _load_purchases_window(user_id, start, end)


def _load_inventory_snapshot(user_id: int) -> pd.DataFrame:
    df = _read_sql(
        """
        SELECT id, name, type, base_unit,
               COALESCE(base_amount,0.0)    AS base_amount,
               COALESCE(price_per_base,0.0) AS price_per_base,
               COALESCE(total_cost,0.0)     AS total_cost,
               COALESCE(expiration,'')      AS expiration
          FROM inventory
         WHERE user_id=?
        """,
        (user_id,),
    )
    df["value"] = df["base_amount"] * df["price_per_base"]
    def _days_left(s: str) -> Optional[int]:
        if not s:
            return None
        try:
            return (pd.to_datetime(s).date() - TODAY).days
        except Exception:
            return None
    df["days_left"] = df["expiration"].apply(_days_left)
    return df


# ------------------------------ AI helpers -----------------------------------

# Robust bucketing helpers to ensure current day/week is always shown and zeros don't explode indexes

def _bucket_index_range(start: date, end: date, bucket: str):
    if bucket == "Day":
        return pd.date_range(start, end, freq="D")
    if bucket == "Week":
        # ISO-style weeks starting Monday
        return pd.date_range(start, end, freq="W-MON")
    # Month start
    return pd.date_range(start.replace(day=1), end, freq="MS")


def _pad_buckets(df: pd.DataFrame, start: date, end: date, bucket: str) -> pd.DataFrame:
    if df is None or df.empty or "bucket" not in df.columns:
        idx = _bucket_index_range(start, end, bucket)
        return pd.DataFrame({"bucket": idx, "waste": [0]*len(idx), "spend": [0]*len(idx)})
    keep = [c for c in ["waste", "spend", "waste_idx", "spend_idx"] if c in df.columns]
    idx = _bucket_index_range(start, end, bucket)
    out = (
        df.set_index("bucket")[keep]
          .reindex(idx, fill_value=0)
          .rename_axis("bucket")
          .reset_index()
    )
    return out


def _safe_index(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return series
    nz = series[series > 0]
    if len(nz) == 0:
        return pd.Series([0] * len(series), index=series.index)
    base = nz.iloc[0]
    if base == 0:
        return pd.Series([0] * len(series), index=series.index)
    return (series / base * 100.0).round(2)



def _ai_call(prompt: str) -> str:
    if OpenAI is None:
        return "AI is not configured. Install openai>=1.0 and set OPENAI_API_KEY in secrets."
    try:
        api_key = st.secrets["OPENAI_API_KEY"]
    except Exception:
        return "OPENAI_API_KEY not found in Streamlit secrets."
    try:
        client = OpenAI(api_key=api_key)
        rsp = client.chat.completions.create(
            model=st.secrets.get("RECIPE_AI_MODEL", "gpt-4o-mini"),
            temperature=0.2,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an operations analyst for food inventory. Be precise, concise, and practical. "
                        "Always format currency with the shekel sign (₪), never $ or USD. Use bullets and numbers."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        )
        return rsp.choices[0].message.content.strip()
    except Exception as e:
        return f"OpenAI call failed: {e}"


def _ai_payload(user_id: int, start: date, end: date) -> dict:
    k = kpis_for_window(user_id, start, end)
    top = top_waste_items(user_id, start, end, limit=10)
    cat = category_split(user_id, start, end)
    heat = daily_heatmap(user_id, start, end)
    return {
        "kpis": k,
        "top": top.to_dict(orient="records") if not top.empty else [],
        "cat": cat.to_dict(orient="records") if not cat.empty else [],
        "heat_days": len(heat) if not heat.empty else 0,
        "window": {"start": str(start), "end": str(end)},
    }


# --------------------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------------------

def page_overview(user_id: int):
    st.header("Overview")
    start, end, bucket = _window_selector(key='ov')
    k = kpis_for_window(user_id, start, end)

    # KPI grid (2 rows of 5, with short captions)
    c = st.columns(5)
    c[0].metric("Total Waste", f"₪{k['waste_total']:,.2f}")
    c[1].metric("Waste vs Spend", f"{k['waste_vs_spend']:.1f}%" if k['waste_vs_spend'] is not None else "—")
    c[2].metric("Waste vs Inventory", f"{k['waste_vs_inventory']:.1f}%" if k['waste_vs_inventory'] is not None else "—")
    c[3].metric("Waste / day", f"₪{k['waste_per_day']:,.2f}")
    c[4].metric("Spend (period)", f"₪{k['spend_total']:,.2f}")

    c = st.columns(5)
    c[0].metric("WoW", f"{k['wow']:+.1f}%" if k['wow'] is not None else "—")
    c[1].metric("MoM", f"{k['mom']:+.1f}%" if k['mom'] is not None else "—")
    c[2].metric("Expiring ≤7d (items)", f"{int(k['expiring_items'])}")
    c[3].metric("Expiring ≤7d (₪)", f"₪{k['expiring_value']:,.2f}")
    c[4].metric("Inventory value", f"₪{k['inventory_value']:,.2f}")

    st.caption("Waste is calculated from actual expired events in the window. Spend is purchases within the same window. Inventory value is current on-hand.")

    st.divider()

    left, right = st.columns([2, 1])

    with left:
        st.subheader("Waste vs Spend trend")
        ser_raw = waste_and_spend_series(user_id, start, end, bucket=bucket)
        ser = _pad_buckets(ser_raw, start, end, bucket)
        if ser.empty:
            st.caption("No data in this window.")
        else:
            view = st.radio("Display as", ["Index", "₪"], horizontal=True, key=f"ov_view_{bucket}")
            if view == "Index":
                ser["Waste idx"] = _safe_index(ser["waste"])
                ser["Spend idx"] = _safe_index(ser["spend"])
                chart = (
                    alt.Chart(ser)
                    .transform_fold(["Waste idx", "Spend idx"], as_=["Series", "Value"])
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("bucket:T", title="Period"),
                        y=alt.Y("Value:Q", title="Index (start=100)"),
                        color=alt.Color("Series:N", title="Series"),
                        tooltip=["bucket:T", alt.Tooltip("Waste idx:Q", title="Waste idx"), alt.Tooltip("Spend idx:Q", title="Spend idx")],
                    )
                )
                st.altair_chart(chart, use_container_width=True)
                st.caption("Indexed to first non‑zero period to avoid divide‑by‑zero insanity.")
            else:
                chart = (
                    alt.Chart(ser)
                    .transform_fold(["waste", "spend"], as_=["Series", "₪"]) 
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("bucket:T", title="Period"),
                        y=alt.Y("₪:Q", title="₪"),
                        color="Series:N",
                        tooltip=["bucket:T", "₪:Q"],
                    )
                )
                st.altair_chart(chart, use_container_width=True)
                st.caption("Absolute ₪ by period, padded so today/week always shows.")

    st.divider()

    g1, g2 = st.columns(2)
    with g1:
        st.subheader("By category")
        cat = category_split(user_id, start, end)
        if cat.empty:
            st.caption("No waste to split.")
        else:
            st.bar_chart(cat.set_index("type")["waste_value"])
            st.caption("Where waste concentrates across categories.")
    with g2:
        st.subheader("Daily waste heatmap")
        heat = daily_heatmap(user_id, start, end)
        if heat.empty:
            st.caption("No waste days to display.")
        else:
            ch = alt.Chart(heat).mark_rect().encode(
                x=alt.X("week:O", title="ISO week"),
                y=alt.Y("dow:O", title="Day of week"),
                color=alt.Color("waste_value:Q", title="Waste ₪"),
                tooltip=["d:T", alt.Tooltip("waste_value:Q", title="₪")],
            )
            st.altair_chart(ch, use_container_width=True)
            st.caption("Calendar pattern of waste — spot bad habits.")


def page_cost_control(user_id: int, key: str = 'cc', show_header: bool = True):
    if show_header:
        st.header("Cost Control")
    start, end, _ = _window_selector(key=key)

    # Spend & waste by store
    purch = _load_purchases_window(user_id, start, end)
    stores_spend = pd.DataFrame()
    if purch is not None and not purch.empty:
        stores_spend = (
            purch.groupby("store_name", as_index=False)["total_paid"].sum().sort_values("total_paid", ascending=False)
        )
    waste = store_waste(user_id, start, end)

    colA, colB, colC, colD = st.columns(4)
    total_spend = float(stores_spend["total_paid"].sum()) if not stores_spend.empty else 0.0
    total_waste = float(waste["waste_value"].sum()) if not waste.empty else 0.0
    colA.metric("Period spend", f"₪{total_spend:,.2f}")
    colB.metric("Period waste", f"₪{total_waste:,.2f}")
    colC.metric("Waste rate", f"{(total_waste/total_spend*100):.1f}%" if total_spend>0 else "—")
    colD.metric("Active stores", f"{stores_spend['store_name'].nunique() if not stores_spend.empty else 0}")

    st.subheader("Spend by store")
    if stores_spend.empty:
        st.caption("No purchases in the selected window.")
    else:
        st.bar_chart(stores_spend.set_index("store_name")["total_paid"])  
        with st.expander("Table"):
            t = stores_spend.copy(); t["₪"] = t["total_paid"].map(lambda x: f"₪{x:,.2f}")
            st.dataframe(t[["store_name","₪"]], use_container_width=True)

    st.subheader("Waste and waste-rate by store")
    if waste.empty and stores_spend.empty:
        st.caption("Not enough data to attribute waste to stores.")
    else:
        m = waste.merge(stores_spend, on="store_name", how="outer").fillna(0)
        m["waste_rate"] = m.apply(lambda r: (r["waste_value"]/r["total_paid"]*100) if r["total_paid"]>0 else 0.0, axis=1)
        m = m.sort_values(["waste_rate","waste_value"], ascending=[False, False])
        st.bar_chart(m.set_index("store_name")["waste_rate"])  
        with st.expander("Details"):
            show = m.copy(); show["Spend ₪"] = show["total_paid"].map(lambda x: f"₪{x:,.2f}")
            show["Waste ₪"] = show["waste_value"].map(lambda x: f"₪{x:,.2f}")
            show["Waste rate %"] = show["waste_rate"].map(lambda x: f"{x:.1f}%")
            st.dataframe(show[["store_name","Spend ₪","Waste ₪","Waste rate %"]], use_container_width=True)

    st.divider()
    st.subheader("Price variance (last 90 days)")
    p90 = _load_purchases_days(user_id, 90)
    if p90.empty:
        st.caption("No purchases in last 90 days.")
    else:
        # median per item overall
        med = (
            p90[p90["unit_price_base"]>0]
            .groupby(["item_id","item_name"], as_index=False)["unit_price_base"].median()
            .rename(columns={"unit_price_base":"median_unit"})
        )
        # store avg price per item
        store_item = (
            p90[p90["unit_price_base"]>0]
            .groupby(["store_name","item_id","item_name"], as_index=False)["unit_price_base"].mean()
            .rename(columns={"unit_price_base":"store_unit"})
        )
        cmp = store_item.merge(med, on=["item_id","item_name"], how="left")
        cmp["uplift_%"] = (cmp["store_unit"] - cmp["median_unit"]) / cmp["median_unit"] * 100
        # aggregate by store weighted by spend share
        weights = p90.groupby(["store_name","item_id"], as_index=False)["total_paid"].sum().rename(columns={"total_paid":"w"})
        cmp = cmp.merge(weights, on=["store_name","item_id"], how="left").fillna({"w":0})
        store_uplift = (
            cmp.groupby("store_name").apply(lambda g: (g["uplift_%"]*g["w"].fillna(0)).sum() / (g["w"].sum() or 1)).reset_index(name="avg_uplift_%")
            .sort_values("avg_uplift_%", ascending=False)
        )
        st.bar_chart(store_uplift.set_index("store_name")["avg_uplift_%"])  
        with st.expander("Offending items by store"):
            top_off = cmp.sort_values("uplift_%", ascending=False).head(20).copy()
            top_off["Median ₪/base"] = top_off["median_unit"].map(lambda x: f"₪{x:,.3f}")
            top_off["Store ₪/base"] = top_off["store_unit"].map(lambda x: f"₪{x:,.3f}")
            top_off["Δ% vs median"] = top_off["uplift_%"].map(lambda x: f"{x:.1f}%")
            st.dataframe(top_off[["store_name","item_name","Median ₪/base","Store ₪/base","Δ% vs median"]], use_container_width=True)


def page_risk_waste(user_id: int):
    st.header("Risk & Waste")
    start, end, _ = _window_selector(key='rw')

    ct, val = expiring_soon(user_id, 7)
    c1, c2 = st.columns(2)
    c1.metric("Expiring ≤7 days (items)", f"{ct}")
    c2.metric("Expiring ≤7 days (₪)", f"₪{val:,.2f}")

    inv = _load_inventory_snapshot(user_id)
    soon = inv[(inv["days_left"].notna()) & (inv["days_left"] >= 0) & (inv["days_left"] <= 14) & (inv["value"] > 0)].copy()
    if soon.empty:
        st.caption("No items expiring in the next 14 days.")
    else:
        soon = soon.sort_values(["days_left","value"], ascending=[True, False])
        soon["Value ₪"] = soon["value"].map(lambda x: f"₪{x:,.2f}")
        st.subheader("Expiring soon (≤14 days)")
        st.dataframe(soon[["name","type","base_unit","base_amount","expiration","days_left","Value ₪"]], use_container_width=True, height=360)
        st.caption("Use/freeze these first; they represent likely loss if unused.")

    st.subheader("Recent waste events")
    we = waste_events(user_id, start, end)
    if we.empty:
        st.caption("No expired events in this window.")
    else:
        show = we[["ts", "name", "qty_ui", "unit_ui", "step_count", "waste_value"]].copy()
        show.rename(columns={"ts": "Date", "name": "Item", "qty_ui": "Qty", "unit_ui": "Unit", "waste_value": "₪"}, inplace=True)
        show["₪"] = show["₪"].map(lambda x: f"₪{x:,.2f}")
        st.dataframe(show.sort_values("Date", ascending=False), use_container_width=True, height=320)


def page_suppliers(user_id: int):
    st.header("Suppliers")
    # Reuse Cost Control visuals with independent widget keys and without extra header
    page_cost_control(user_id, key='sup', show_header=False)


def page_trends(user_id: int):
    st.header("Trends")
    start, end, bucket = _window_selector(key='tr')

    st.subheader("Waste vs Spend over time")
    ser_raw = waste_and_spend_series(user_id, start, end, bucket=bucket)
    ser = _pad_buckets(ser_raw, start, end, bucket)
    if ser.empty:
        st.caption("No data to chart.")
    else:
        view = st.radio("Display as", ["Index", "₪"], horizontal=True, key=f"tr_view_{bucket}")
        if view == "Index":
            ser["Waste idx"] = _safe_index(ser["waste"])
            ser["Spend idx"] = _safe_index(ser["spend"])
            chart = (
                alt.Chart(ser)
                .transform_fold(["Waste idx", "Spend idx"], as_=["Series", "Value"])
                .mark_line(point=True)
                .encode(x=alt.X("bucket:T", title="Period"), y=alt.Y("Value:Q", title="Index (start=100)"), color="Series:N", tooltip=["bucket:T", "Value:Q"]) 
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            chart = (
                alt.Chart(ser)
                .transform_fold(["waste", "spend"], as_=["Series", "₪"]).mark_line(point=True)
                .encode(x=alt.X("bucket:T", title="Period"), y=alt.Y("₪:Q", title="₪"), color="Series:N", tooltip=["bucket:T", "₪:Q"]) 
            )
            st.altair_chart(chart, use_container_width=True)
        st.caption("Padded buckets ensure the current day/week is included even if value is 0.")


def page_ai(user_id: int):
    st.header("AI Summary")
    start, end, _ = _window_selector(key='ai')

    payload = _ai_payload(user_id, start, end)
    prompt = f"""Summarize the following inventory and waste metrics succinctly. Call out the top issues and give 3–6 concrete actions (verbs + targets). If data looks sparse or noisy, say so.

WINDOW: {payload['window']}
KPIS: {payload['kpis']}
TOP_ITEMS: {payload['top']}
BY_CATEGORY: {payload['cat']}
DAYS_WITH_WASTE: {payload['heat_days']}
"""

    st.subheader("Executive summary")
    with st.spinner("Thinking..."):
        ans = _ai_call(prompt)
    ans = (ans or "").replace("USD", "₪").replace("$", "₪")
    st.markdown(ans)

    st.divider()
    st.subheader("Ask a question about the data")
    q = st.text_input("e.g., Which 3 items should I order less of next month?", key="ai_q")
    if q:
        with st.spinner("Thinking..."):
            q_prompt = f"""Answer using only this data; if uncertain, say what else is needed.
QUESTION: {q}
WINDOW: {payload['window']}
KPIS: {payload['kpis']}
TOP_ITEMS: {payload['top']}
BY_CATEGORY: {payload['cat']}
DAYS_WITH_WASTE: {payload['heat_days']}
"""
            ans_q = _ai_call(q_prompt)
        ans_q = (ans_q or "").replace("USD", "₪").replace("$", "₪")
        st.markdown(ans_q)


def page_audit(user_id: int):
    st.header("Audit")
    start, end, _ = _window_selector(key='au')

    s = sanity_report(user_id, start, end)
    c1, c2 = st.columns(2)
    c1.metric("Expired with zero value", s.get("expired_zero_value", 0))
    c2.metric("Items with zero price", s.get("items_zero_price", 0))

    st.subheader("Event list (expired)")
    we = waste_events(user_id, start, end)
    if we.empty:
        st.caption("No expired events in this window.")
    else:
        show = we[["ts", "name", "qty_ui", "unit_ui", "step_count", "waste_value"]].copy()
        show.rename(columns={"ts": "Date", "name": "Item", "qty_ui": "Qty", "unit_ui": "Unit", "waste_value": "₪"}, inplace=True)
        show["₪"] = show["₪"].map(lambda x: f"₪{x:,.2f}")
        st.dataframe(show.sort_values("Date", ascending=False), use_container_width=True, height=420)


def page_guide(user_id: int):
    st.header("Guide")
    st.markdown(
        """
### How to read this dashboard

**Total Waste** — shekel value of items marked *expired* in the selected window. Keep trending down.

**Waste vs Spend** — percent of purchases that ended up wasted: `waste / spend` for the window. Under 5% is solid; above 10% needs action.

**Waste vs Inventory** — percent of current on-hand value that has already expired. If this is rising, your par levels are off or rotation is failing.

**Waste / day** — daily burn rate based on the window. Use it to forecast monthly loss.

**Expiring ≤7d** — items and value likely to be lost within a week unless used/frozen/repurposed.

**Trends** — look at the slope of Waste vs Spend. A rising Waste index while Spend is flat means process issues; both rising together usually means overbuying.

**Cost Control** — identifies stores and items with price uplift vs your own 90‑day median. Use it to renegotiate or switch suppliers.

**Audit** — flags data problems (zero prices, zero-valued expired events). Fix these before trusting any analysis.

**AI Summary** — quick narrative of the above. It only knows what the data shows; if something seems off, check Audit and your item prices.
        """
    )


# --------------------------------------------------------------------------------------
# Router (top tabs like the rest of the app)
# --------------------------------------------------------------------------------------

def main():
    user_id = _resolve_user_id()

    st.title("📊 Dashboard")
    tabs = st.tabs(["Overview", "Cost Control", "Risk & Waste", "Suppliers", "Trends", "AI Summary", "Audit", "Guide"]) 

    with tabs[0]:
        page_overview(user_id)
    with tabs[1]:
        page_cost_control(user_id)
    with tabs[2]:
        page_risk_waste(user_id)
    with tabs[3]:
        page_suppliers(user_id)
    with tabs[4]:
        page_trends(user_id)
    with tabs[5]:
        page_ai(user_id)
    with tabs[6]:
        page_audit(user_id)
    with tabs[7]:
        page_guide(user_id)


def dashboard():
    main()


def app():
    main()


app = dashboard

if __name__ == "__main__":
    main()
