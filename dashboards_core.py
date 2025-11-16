# dashboards_core.py
# Core data access and analytics for dashboards. Zero UI. Safe waste math.
# Usage (UI): from dashboards_core import *

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional, Tuple, List, Dict

import numpy as np
import pandas as pd
from db import get_connection

# --------------------------------------------------------------------------------------
# Low-level helpers
# --------------------------------------------------------------------------------------

TODAY = date.today()


def _read_sql(sql: str, params: Tuple = ()) -> pd.DataFrame:
    con = get_connection()
    try:
        return pd.read_sql_query(sql, con, params=params)
    finally:
        con.close()


# Minimal unit conversion (tight deadline edition)
_UNIT_MAP = {
    "g": ("g", 1.0),
    "kg": ("g", 1000.0),
    "ml": ("ml", 1.0),
    "l": ("ml", 1000.0),
    "pcs": ("pcs", 1.0),
    "pc": ("pcs", 1.0),
    "unit": ("pcs", 1.0),
}


def _to_base(qty: float, unit: Optional[str], base_unit: str) -> float:
    if qty is None:
        return 0.0
    try:
        q = float(qty)
    except Exception:
        return 0.0
    u = (unit or base_unit or "pcs").lower()
    bu, factor = _UNIT_MAP.get(u, (base_unit, 1.0))
    if bu != base_unit:
        # refuse nonsense conversions like g->ml
        return q
    return q * factor


# --------------------------------------------------------------------------------------
# Domain loaders
# --------------------------------------------------------------------------------------

def load_inventory(user_id: int) -> pd.DataFrame:
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
    df["inv_value"] = df["base_amount"] * df["price_per_base"]
    return df


def load_usage_all(user_id: int) -> pd.DataFrame:
    return _read_sql(
        """
        SELECT u.item_id, u.event_type,
               COALESCE(u.step_count,0)     AS step_count,
               COALESCE(u.quantity,0.0)     AS qty_ui,
               COALESCE(u.unit,'')          AS unit_ui,
               COALESCE(u.value_shekel,0.0) AS value_shekel,
               u.ts,
               i.name, i.base_unit, COALESCE(i.price_per_base,0) AS price_per_base
          FROM usage_log u
          JOIN inventory i ON i.id = u.item_id
         WHERE u.user_id=?
        """,
        (user_id,),
    )


def load_purchases_all(user_id: int) -> pd.DataFrame:
    return _read_sql(
        """
        SELECT p.item_id, p.qty_base, p.unit_price_base, p.total_paid, p.ts,
               i.name, i.type, i.base_unit,
               COALESCE(s.name,'') AS store_name
          FROM purchases_log p
          LEFT JOIN inventory i ON i.id = p.item_id
          LEFT JOIN stores s    ON s.id = p.store_id
         WHERE p.user_id=?
        """,
        (user_id,),
    )


# --------------------------------------------------------------------------------------
# Price lookups
# --------------------------------------------------------------------------------------

def _median_unit_price(purch: pd.DataFrame, item_id: int) -> Optional[float]:
    if purch is None or purch.empty:
        return None
    p = purch[purch["item_id"] == item_id]
    if p.empty:
        return None
    m = float(p["unit_price_base"].median())
    return m if m > 0 else None


def _last_unit_price_before(purch: pd.DataFrame, item_id: int, when: pd.Timestamp) -> Optional[float]:
    if purch is None or purch.empty:
        return None
    p = purch[purch["item_id"] == item_id].copy()
    if p.empty:
        return None
    p["ts_dt"] = pd.to_datetime(p["ts"], errors="coerce")
    at_or_before = p[p["ts_dt"] <= when]
    if not at_or_before.empty:
        return float(at_or_before.sort_values("ts_dt").iloc[-1]["unit_price_base"]) or None
    return float(p.sort_values("ts_dt").iloc[-1]["unit_price_base"]) or None


# --------------------------------------------------------------------------------------
# Waste valuation (robust)
# --------------------------------------------------------------------------------------

def waste_events(user_id: int, start: date, end: date) -> pd.DataFrame:
    """Return expired events within [start, end] with a safe waste_value.
    Priority:
      1) use value_shekel if present (>0)
      2) else use qty_ui converted to base × price
      3) else treat step_count as BASE units (no 100× UI multiplier)
    Price:
      - prefer last purchase unit_price_base at/before event
      - else inventory.price_per_base
      - clamp fallback if >10× median unit price
    """
    usage = load_usage_all(user_id)
    if usage.empty:
        return pd.DataFrame(columns=["ts","item_id","name","waste_value"])

    usage["ts_dt"] = pd.to_datetime(usage["ts"], errors="coerce")
    m = (usage["event_type"] == "expired") & (usage["ts_dt"].dt.date >= start) & (usage["ts_dt"].dt.date <= end)
    expd = usage[m].copy()
    if expd.empty:
        return pd.DataFrame(columns=["ts","item_id","name","waste_value"])

    inv = load_inventory(user_id)
    purch = load_purchases_all(user_id)

    inv_small = inv[["id","name","base_unit","price_per_base"]].rename(columns={"id":"item_id"})
    expd = expd.merge(inv_small, on="item_id", how="left", suffixes=("","_inv"))

    # initial value
    expd["waste_value"] = pd.to_numeric(expd["value_shekel"], errors="coerce").fillna(0.0)

    need = expd["waste_value"] <= 0
    if need.any():
        def compute_row(row):
            when = row["ts_dt"]
            base_unit = (row.get("base_unit") or "pcs").lower()
            # quantity
            if float(row.get("qty_ui") or 0.0) > 0 and str(row.get("unit_ui") or ""):  # use true qty
                base_qty = _to_base(float(row["qty_ui"]), str(row["unit_ui"]), base_unit)
            else:
                # fall back to treating step_count as base units to avoid 100× explosions
                base_qty = float(row.get("step_count") or 0.0)
            # price
            price = _last_unit_price_before(purch, int(row["item_id"]), when) or float(row.get("price_per_base") or 0.0)
            if price <= 0:
                return 0.0
            # clamp vs median
            med = _median_unit_price(purch, int(row["item_id"]))
            if med and price > med * 10:
                price = med
            return base_qty * price
        expd.loc[need, "waste_value"] = expd.loc[need].apply(compute_row, axis=1)

    # keep sane columns
    cols = [
        "ts_dt","ts","item_id","name","base_unit","qty_ui","unit_ui","step_count","price_per_base","waste_value"
    ]
    return expd[cols]


# --------------------------------------------------------------------------------------
# KPI bundles and trends
# --------------------------------------------------------------------------------------

def purchases_sum(user_id: int, start: date, end: date) -> float:
    purch = load_purchases_all(user_id)
    if purch.empty:
        return 0.0
    purch["ts_dt"] = pd.to_datetime(purch["ts"], errors="coerce")
    m = (purch["ts_dt"].dt.date >= start) & (purch["ts_dt"].dt.date <= end)
    return float(purch.loc[m, "total_paid"].sum())


def inventory_value(user_id: int) -> float:
    inv = load_inventory(user_id)
    if inv.empty:
        return 0.0
    return float(inv["inv_value"].sum())


def expiring_soon(user_id: int, days: int = 7) -> Tuple[int, float]:
    inv = load_inventory(user_id)
    if inv.empty:
        return 0, 0.0
    def days_until(exp_str: Optional[str]) -> Optional[int]:
        if not exp_str:
            return None
        try:
            d = datetime.fromisoformat(exp_str).date()
            return (d - TODAY).days
        except Exception:
            return None
    inv["days_left"] = inv["expiration"].apply(days_until)
    m = inv["days_left"].notna() & (inv["days_left"] >= 0) & (inv["days_left"] <= days) & (inv["base_amount"] > 0)
    return int(m.sum()), float(inv.loc[m, "inv_value"].sum())


def kpis_for_window(user_id: int, start: date, end: date) -> Dict[str, float]:
    we = waste_events(user_id, start, end)
    waste_total = float(we["waste_value"].sum()) if not we.empty else 0.0
    spend_total = purchases_sum(user_id, start, end)
    inv_val = inventory_value(user_id)

    days = max(1, (end - start).days)
    waste_per_day = waste_total / days

    # deltas
    length = (end - start).days
    prev_start = start - timedelta(days=length)
    prev_end = start
    prev_waste = float(waste_events(user_id, prev_start, prev_end)["waste_value"].sum()) if length > 0 else 0.0
    def pct_change(curr, prev):
        if prev is None or prev == 0:
            return None
        return (curr - prev) / prev * 100.0
    wow = pct_change(float(waste_events(user_id, end - timedelta(days=7), end)["waste_value"].sum()),
                     float(waste_events(user_id, end - timedelta(days=14), end - timedelta(days=7))["waste_value"].sum()))
    # month over month
    this_month_start = end.replace(day=1)
    prev_month_end = this_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    mom = pct_change(
        float(waste_events(user_id, this_month_start, end)["waste_value"].sum()),
        float(waste_events(user_id, prev_month_start, prev_month_end)["waste_value"].sum()),
    )

    exp_ct, exp_val = expiring_soon(user_id, 7)

    return {
        "waste_total": waste_total,
        "waste_per_day": waste_per_day,
        "waste_vs_spend": (waste_total / spend_total * 100.0) if spend_total > 0 else None,
        "waste_vs_inventory": (waste_total / inv_val * 100.0) if inv_val > 0 else None,
        "wow": wow,
        "mom": mom,
        "expiring_items": exp_ct,
        "expiring_value": exp_val,
        "spend_total": spend_total,
        "inventory_value": inv_val,
    }


def time_bucket(series_df: pd.DataFrame, ts_col: str, val_col: str, bucket: str) -> pd.DataFrame:
    if series_df.empty:
        return pd.DataFrame({"bucket": [], val_col: []})
    df = series_df.copy()
    df["_ts"] = pd.to_datetime(df[ts_col], errors="coerce")
    if bucket == "Day":
        df["bucket"] = df["_ts"].dt.date
    elif bucket == "Week":
        df["bucket"] = df["_ts"].dt.to_period("W").apply(lambda r: r.start_time.date())
    else:
        df["bucket"] = df["_ts"].dt.to_period("M").apply(lambda r: r.start_time.date())
    g = df.groupby("bucket", as_index=False)[val_col].sum().sort_values("bucket")
    return g


def waste_and_spend_series(user_id: int, start: date, end: date, bucket: str = "Day") -> pd.DataFrame:
    we = waste_events(user_id, start, end)
    purch = load_purchases_all(user_id)
    if not purch.empty:
        purch = purch.copy()
        purch = purch[(pd.to_datetime(purch["ts"], errors="coerce").dt.date >= start) & (pd.to_datetime(purch["ts"], errors="coerce").dt.date <= end)]
    w_b = time_bucket(we, "ts_dt", "waste_value", bucket)
    s_b = time_bucket(purch, "ts", "total_paid", bucket) if not (purch is None or purch.empty) else pd.DataFrame({"bucket": [], "total_paid": []})
    out = pd.merge(w_b.rename(columns={"waste_value": "waste"}), s_b.rename(columns={"total_paid": "spend"}), on="bucket", how="outer").fillna(0).sort_values("bucket")
    # index=100 at first bucket if nonzero
    if not out.empty:
        base_w = out.iloc[0]["waste"] or 1.0
        base_s = out.iloc[0]["spend"] or 1.0
        out["waste_idx"] = out["waste"] / base_w * 100.0
        out["spend_idx"] = out["spend"] / base_s * 100.0
    return out


def top_waste_items(user_id: int, start: date, end: date, limit: int = 10) -> pd.DataFrame:
    we = waste_events(user_id, start, end)
    if we.empty:
        return pd.DataFrame(columns=["name","waste_value"])
    g = we.groupby("name", as_index=False)["waste_value"].sum().sort_values("waste_value", ascending=False)
    return g.head(limit)


def category_split(user_id: int, start: date, end: date) -> pd.DataFrame:
    we = waste_events(user_id, start, end)
    if we.empty:
        return pd.DataFrame(columns=["type","waste_value"])
    inv = load_inventory(user_id)[["id","type","name"]].rename(columns={"id":"item_id"})
    m = we.merge(inv, on=["item_id","name"], how="left")
    g = m.groupby("type", as_index=False)["waste_value"].sum().sort_values("waste_value", ascending=False)
    g["type"].fillna("Unknown", inplace=True)
    return g


def store_waste(user_id: int, start: date, end: date) -> pd.DataFrame:
    we = waste_events(user_id, start, end)
    purch = load_purchases_all(user_id)
    if we.empty or purch.empty:
        return pd.DataFrame(columns=["store_name","waste_value"])
    purch = purch.copy()
    purch["ts_dt"] = pd.to_datetime(purch["ts"], errors="coerce")
    # attribute each waste event to last store that sold this item before event timestamp
    def store_for_event(item_id: int, when: pd.Timestamp) -> str:
        rows = purch[(purch["item_id"] == item_id) & (purch["ts_dt"] <= when)].sort_values("ts_dt")
        if rows.empty:
            return "Unknown"
        s = str(rows.iloc[-1]["store_name"] or "Unknown")
        return s if s else "Unknown"
    if not we.empty:
        we["store_name"] = we.apply(lambda r: store_for_event(int(r["item_id"]), pd.to_datetime(r["ts_dt"])), axis=1)
    g = we.groupby("store_name", as_index=False)["waste_value"].sum().sort_values("waste_value", ascending=False)
    return g


def daily_heatmap(user_id: int, start: date, end: date) -> pd.DataFrame:
    we = waste_events(user_id, start, end)
    if we.empty:
        return pd.DataFrame(columns=["d","waste_value","dow","week"])
    we["d"] = we["ts_dt"].dt.date
    g = we.groupby("d", as_index=False)["waste_value"].sum()
    g["dow"] = pd.to_datetime(g["d"]).dt.weekday
    g["week"] = pd.to_datetime(g["d"]).dt.isocalendar().week
    return g


def sanity_report(user_id: int, start: date, end: date) -> Dict[str, int]:
    usage = load_usage_all(user_id)
    if usage.empty:
        return {"expired_zero_value": 0, "items_zero_price": 0}
    usage["ts_dt"] = pd.to_datetime(usage["ts"], errors="coerce")
    m = (usage["event_type"] == "expired") & (usage["ts_dt"].dt.date >= start) & (usage["ts_dt"].dt.date <= end)
    expired_zero_value = int((usage.loc[m, "value_shekel"] <= 0).sum())
    inv = load_inventory(user_id)
    items_zero_price = int((inv["price_per_base"] <= 0).sum())
    return {"expired_zero_value": expired_zero_value, "items_zero_price": items_zero_price}
