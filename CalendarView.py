# CalendarView.py — Homepage (post-login) polished with KPIs and AI welcome
# Keeps your existing banner image logic. Adds accurate KPIs, expiring summaries,
# human-readable recent activity, and an OpenAI-powered personal welcome.
# Exposes calendar_view(), render(), and app() entrypoints.

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
import pandas as pd
import db

# Optional analytics (fallbacks if dashboards_core is not present)
try:
    from dashboards_core import TODAY, kpis_for_window, expiring_soon
except Exception:  # pragma: no cover
    TODAY = date.today()

    def kpis_for_window(*_, **__):
        return {
            "waste_total": 0.0,
            "waste_vs_spend": None,
            "waste_vs_inventory": None,
            "waste_per_day": 0.0,
            "spend_total": 0.0,
            "wow": None,
            "mom": None,
            "expiring_items": 0,
            "expiring_value": 0.0,
            "inventory_value": 0.0,
        }

    def expiring_soon(*_, **__):
        return 0, 0.0

# Optional OpenAI (graceful fallback)
try:
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None

# Banner assets folder (uses your existing images — we DO NOT change them)
ASSETS_DIR = Path(__file__).parent / "assets" / "banners"

# -----------------------------------------------------------------------------
# Utils
# -----------------------------------------------------------------------------

def _days_left(d: date) -> int:
    return (d - date.today()).days


def _parse_date(x: Any) -> date:
    if isinstance(x, date):
        return x
    try:
        return datetime.fromisoformat(str(x)).date()
    except Exception:
        try:
            return datetime.strptime(str(x), "%Y-%m-%d").date()
        except Exception:
            return date.today()


def _badge(text: str, bg="#243042", fg="#cfe3ff") -> str:
    return (
        "<span style='padding:2px 8px;border-radius:10px;"
        f"background:{bg};color:{fg};font-size:12px'>{text}</span>"
    )


def _risk_tag(d: date) -> str:
    left = _days_left(d)
    if left < 0:
        return _badge("expired", "#3b0a0a", "#ffd1d1")
    if left == 0:
        return _badge("today", "#5b1a1a", "#ffd1d1")
    if left <= 2:
        return _badge("very soon", "#5b3a1a", "#ffe7c2")
    if left <= 7:
        return _badge("this week", "#1e293b", "#cfe3ff")
    return _badge(f"in {left}d", "#111827", "#e5e7eb")


# Quantity helpers for recent activity (fixes the 4000 apples problem)

def _friendly_qty(amount: float, unit: str) -> Tuple[float, str]:
    u = (unit or "").lower()
    if u in ("g", "gram", "grams"):
        return (amount / 1000.0, "kg") if amount >= 1000 else (amount, "g")
    if u in ("ml", "milliliter", "millilitre"):
        return (amount / 1000.0, "l") if amount >= 1000 else (amount, "ml")
    return amount, (unit or "pcs")


def _format_qty(qty_ui: float, unit_ui: str, step_count: float, base_unit: str) -> str:
    base_unit = (base_unit or "pcs").lower()
    if qty_ui and float(qty_ui) > 0:
        q, u = _friendly_qty(float(qty_ui), unit_ui or base_unit)
    else:
        # Treat step_count as ALREADY in base units to avoid 100× explosions.
        base_amt = float(step_count or 0.0)
        q, u = _friendly_qty(base_amt, base_unit)
    if u in ("kg", "l"):
        return f"{q:,.1f} {u}" if q < 10 else f"{q:,.0f} {u}"
    if u == "pcs":
        return f"{q:,.0f} pcs"
    return f"{q:,.1f} {u}"


# -----------------------------------------------------------------------------
# Banner handling (keeps existing pictures)
# -----------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _load_banner_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except Exception:
        return None


def _banner_for_now() -> Path:
    hr = datetime.now().hour
    # 5-11 morning, 11-17 afternoon, 17-21 evening, else night
    if 5 <= hr < 11:
        p = ASSETS_DIR / "banner_morning.png"
    elif 11 <= hr < 17:
        p = ASSETS_DIR / "banner_afternoon.png"
    elif 17 <= hr < 21:
        p = ASSETS_DIR / "banner_evening.png"
    else:
        p = ASSETS_DIR / "banner_night.png"
    return p


def _render_time_banner(user_name: str) -> None:
    p = _banner_for_now()
    data = _load_banner_bytes(p)
    if data:
        st.markdown(
            """
            <style>
              .hero-img img { border-radius: 18px; }
            </style>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("<div class='hero-img'>", unsafe_allow_html=True)
        st.image(data, use_container_width=True, caption=f"Welcome, {user_name}")
        st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.title("🏠 Home")


# -----------------------------------------------------------------------------
# User resolution
# -----------------------------------------------------------------------------

def _resolve_user() -> Optional[Dict[str, Any]]:
    try:
        if hasattr(db, "get_current_user"):
            u = db.get_current_user()
            if isinstance(u, dict) and (u.get("id") or u.get("user_id")):
                return {
                    "id": int(u.get("id") or u.get("user_id")),
                    "name": u.get("name") or u.get("user_name") or u.get("phone") or "User",
                }
    except Exception:
        pass
    if "user_id" in st.session_state:
        return {
            "id": int(st.session_state["user_id"]),
            "name": st.session_state.get("user_name") or st.session_state.get("name") or st.session_state.get("phone") or "User",
        }
    return None


# -----------------------------------------------------------------------------
# Data access
# -----------------------------------------------------------------------------

def _inventory_rows(user_id: int) -> List[tuple]:
    """Returns rows: (id, name, expiration, type, qty, unit)"""
    conn = db.get_connection(); c = conn.cursor()
    c.execute(
        """
        SELECT id,
               COALESCE(name,'') as name,
               COALESCE(expiration, date('now')) as expiration,
               COALESCE(type,'Other') as type,
               COALESCE(base_amount, amount, 0) as qty,
               COALESCE(base_unit, unit, 'pcs') as unit
          FROM inventory
         WHERE user_id=?
        """,
        (user_id,),
    )
    rows = c.fetchall(); conn.close()
    return rows


def _recent_activity(user_id: int, limit: int = 5) -> List[Tuple[str, str, str]]:
    """Returns recent rows formatted: (ts_iso, line_text, emoji)."""
    conn = db.get_connection(); c = conn.cursor()
    try:
        c.execute(
            """
            SELECT u.ts, u.event_type,
                   COALESCE(u.step_count,0)     AS step_count,
                   COALESCE(u.quantity,0.0)     AS qty_ui,
                   COALESCE(u.unit,'')          AS unit_ui,
                   i.name, COALESCE(i.base_unit,'pcs') AS base_unit
              FROM usage_log u
              JOIN inventory i ON i.id = u.item_id
             WHERE u.user_id=?
             ORDER BY u.ts DESC
             LIMIT ?
            """,
            (user_id, limit),
        )
        rows = c.fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()

    out: List[Tuple[str, str, str]] = []
    for ts, ev, step_count, qty_ui, unit_ui, name, base_unit in rows or []:
        dt = str(ts)[:19]
        ev = (ev or "").lower()
        line_qty = _format_qty(qty_ui, unit_ui, step_count, base_unit)
        emoji = "✅" if ev == "used" else ("⛔" if ev == "expired" else "➕")
        out.append((dt, f"**{name}** · {ev} · {line_qty}", emoji))
    return out


# -----------------------------------------------------------------------------
# AI welcome message
# -----------------------------------------------------------------------------

def _ai_welcome(user_name: str, user_id: int) -> str:
    """Generate a short, friendly welcome with concrete suggestions.
    Always outputs in ₪ (replace $/USD if model tries)."""
    # Prepare tiny payload from KPIs
    start = TODAY - timedelta(days=30); end = TODAY
    k = kpis_for_window(user_id, start, end)
    meta = {
        "window": {"start": str(start), "end": str(end)},
        "inventory_value": float(k.get("inventory_value") or 0),
        "waste_30d": float(k.get("waste_total") or 0),
        "spend_30d": float(k.get("spend_total") or 0),
        "waste_vs_spend": k.get("waste_vs_spend"),
        "expiring_items": int(k.get("expiring_items") or 0),
        "expiring_value": float(k.get("expiring_value") or 0),
    }

    if OpenAI is None:
        # Friendly fallback
        wvs = meta["waste_vs_spend"]
        wvs_txt = f"{wvs:.1f}%" if isinstance(wvs, (int, float)) and wvs is not None else "—"
        return (
            f"Hi {user_name}. Welcome back. Quick pulse: inventory is ₪{meta['inventory_value']:,.0f}, "
            f"spend 30d ₪{meta['spend_30d']:,.0f}, waste 30d ₪{meta['waste_30d']:,.0f} (rate {wvs_txt}). "
            f"You have {meta['expiring_items']} items expiring soon worth ₪{meta['expiring_value']:,.0f}."
        )

    try:
        api_key = st.secrets["OPENAI_API_KEY"]
        client = OpenAI(api_key=api_key)
        model = st.secrets.get("RECIPE_AI_MODEL", "gpt-4o-mini")
        prompt = (
            "Write a short welcome (3–5 sentences) for an inventory dashboard homepage. "
            "Use the user's first name. Use the shekel sign (₪) for currency. "
            "Tone: pragmatic and warm, not salesy. Include 2–3 concrete suggestions based on the metrics.\n\n"
            f"USER: {user_name}\nMETA: {meta}"
        )
        rsp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": "You are a concise operations analyst."},
                {"role": "user", "content": prompt},
            ],
        )
        text = rsp.choices[0].message.content.strip()
        return text.replace("USD", "₪").replace("$", "₪")
    except Exception as e:
        return f"Welcome {user_name}. (AI unavailable: {e})"


# -----------------------------------------------------------------------------
# Sections
# -----------------------------------------------------------------------------

def _render_header(user_name: str) -> None:
    _render_time_banner(user_name)
    st.caption(f"Today is {date.today():%A, %d %B %Y}.")


def _render_kpis(user_id: int) -> None:
    start = TODAY - timedelta(days=30); end = TODAY
    k = kpis_for_window(user_id, start, end)

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Inventory value", f"₪{float(k.get('inventory_value') or 0):,.0f}")
    c2.metric("Spend 30d", f"₪{float(k.get('spend_total') or 0):,.0f}")
    c3.metric("Waste 30d", f"₪{float(k.get('waste_total') or 0):,.0f}")
    wvs = k.get("waste_vs_spend")
    if wvs is not None:
        c4.metric("Waste vs Spend", f"{float(wvs):.1f}%")
    else:
        c4.metric("Waste vs Spend", "—")
    c5.metric("Expiring ≤7d", f"{int(k.get('expiring_items') or 0)}")
    c6.metric("Expiring ≤7d (₪)", f"₪{float(k.get('expiring_value') or 0):,.0f}")
    st.caption("KPIs are computed over the last 30 days unless marked otherwise.")


def _render_daily_tip(user_id: int) -> None:
    # Minimal contextual nudge without copying SmartCoach
    ct, val = expiring_soon(user_id, 7)
    if ct > 0:
        st.info(f"Heads up: {ct} item(s) worth ₪{val:,.0f} expire within 7 days. Plan usage or freeze.")
    else:
        st.info("No near‑term expiries. Consider reviewing par levels to keep stock lean.")


def _render_expiring_week(rows: List[tuple]) -> None:
    st.subheader("⏳ Expiring this week")
    today = date.today(); horizon = today + timedelta(days=7)
    upcoming: List[Tuple[str, date, str]] = []
    for _id, name, exp, typ, qty, unit in rows:
        try:
            if float(qty or 0) <= 0:
                continue
        except Exception:
            continue
        d = _parse_date(exp)
        if today <= d <= horizon:
            upcoming.append((name, d, typ))
    if not upcoming:
        st.caption("Nothing expiring in the next 7 days.")
        return
    upcoming.sort(key=lambda t: (t[1], t[0]))
    for name, d, typ in upcoming[:5]:
        st.markdown(f"- **{name}** · *{typ}* · {d.isoformat()} &nbsp; {_risk_tag(d)}", unsafe_allow_html=True)
    extra = max(0, len(upcoming) - 5)
    if extra:
        st.caption(f"…and {extra} more this week.")


def _render_activity(user_id: int) -> None:
    st.subheader("🗂 Recent activity")
    rows = _recent_activity(user_id, limit=6)
    if not rows:
        st.caption("No recent activity yet.")
        return
    for ts, txt, emoji in rows:
        st.write(f"{emoji} {ts} — {txt}")


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def calendar_view() -> None:
    user = _resolve_user()
    if not user:
        st.info("Please log in to see your homepage.")
        return

    user_id = int(user["id"])
    raw_name = str(user.get("name") or "User").strip()
    user_name = raw_name if raw_name else "User"
    display_name = (user_name.split()[0].capitalize() if user_name else "User")

    # Header + banner (keeps your picture)
    _render_header(display_name)

    # KPI row and AI welcome
    _render_kpis(user_id)
    st.subheader("Welcome")
    msg = _ai_welcome(display_name, user_id)
    st.markdown(msg)

    # Three core sections
    rows = _inventory_rows(user_id)
    _render_daily_tip(user_id)
    st.divider()
    _render_expiring_week(rows)
    st.divider()
    _render_activity(user_id)


# Compatibility aliases

def render():
    calendar_view()


def app():
    calendar_view()


if __name__ == "__main__":
    calendar_view()
