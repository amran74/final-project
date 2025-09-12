# CalendarView.py — Homepage with Time-of-Day Banner
# Sections:
#   - Hero banner (changes with hour)
#   - Notifications (today + next 3 days)
#   - Expiring this week (top 5)
#   - Recent activity (last 5)
#   - Quick links
#   - Optional week calendar (expander)

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import streamlit as st
import db

# Optional calendar widget
try:
    from streamlit_calendar import calendar as _calendar
except Exception:
    _calendar = None

# Banner assets folder (commit images to: assets/banners/)
ASSETS_DIR = Path(__file__).parent / "assets" / "banners"

# --------------------------------------------------------------------------------
# Utils
# --------------------------------------------------------------------------------
def _days_left(d: date) -> int:
    return (d - date.today()).days

def _parse_date(x: Any) -> date:
    if isinstance(x, date):
        return x
    try:
        return datetime.fromisoformat(str(x)).date()
    except Exception:
        # Try common YYYY-MM-DD
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

# --------------------------------------------------------------------------------
# Banner handling
# --------------------------------------------------------------------------------
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
        return ASSETS_DIR / "banner_morning.png"
    if 11 <= hr < 17:
        return ASSETS_DIR / "banner_afternoon.png"
    if 17 <= hr < 21:
        return ASSETS_DIR / "banner_evening.png"
    return ASSETS_DIR / "banner_night.png"

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
        with st.container():
            st.markdown("<div class='hero-img'>", unsafe_allow_html=True)
            st.image(data, use_container_width=True, caption=f"Welcome, {user_name}")
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        # If no asset found, fall back to a simple title
        st.title("🏠 Home")

# --------------------------------------------------------------------------------
# User resolution
# --------------------------------------------------------------------------------
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

# --------------------------------------------------------------------------------
# Data access
# --------------------------------------------------------------------------------
def _inventory_rows(user_id: int) -> List[tuple]:
    """
    Returns rows: (id, name, expiration, type, qty, unit)
    """
    conn = db.get_connection(); c = conn.cursor()
    c.execute(
        """
        SELECT
          id,
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
    rows = c.fetchall()
    conn.close()
    return rows

def _recent_activity(user_id: int, limit: int = 5) -> List[Tuple[str, str, float, str]]:
    """
    Returns recent rows: (ts_iso, event_type, qty, name)
    """
    conn = db.get_connection(); c = conn.cursor()
    try:
        c.execute(
            """
            SELECT u.ts, u.event_type, u.step_count, i.name
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
    out: List[Tuple[str, str, float, str]] = []
    for ts, ev, qty, nm in rows or []:
        t = str(ts)[:19]
        ev = (ev or "").lower()
        try:
            q = float(qty or 0.0)
        except Exception:
            q = 0.0
        out.append((t, ev, q, nm or ""))
    return out

def _coach_counts(user_id: int) -> Tuple[List[dict], List[dict]]:
    """
    Returns (critical_list, urgent_list)
    critical_list: items expiring today/expired
    urgent_list: items expiring in 1–3 days
    Fallback to empty lists if core missing.
    """
    try:
        import smartcoach_core as core
        crit = core.get_critical_warnings(user_id)
        today_expired = (crit.get("expired", []) or []) + (crit.get("today", []) or [])
        urgent = core.get_urgent_risks(user_id, window_days=3, limit=50) or []
        return today_expired, urgent
    except Exception:
        return [], []

# --------------------------------------------------------------------------------
# Minimal sections
# --------------------------------------------------------------------------------
def _render_header(user_name: str) -> None:
    # Banner first; if banner is missing, title is shown in _render_time_banner
    _render_time_banner(user_name)
    # Subtle date line
    st.caption(f"Today is {date.today():%A, %d %B %Y}.")

def _render_notifications(user_id: int) -> None:
    st.subheader("🔔 Notifications")
    critical, urgent = _coach_counts(user_id)

    if not critical and not urgent:
        st.success("All clear. Nothing urgent right now.")
        return

    cols = st.columns(2)
    with cols[0]:
        st.markdown("**Today**")
        if not critical:
            st.caption("No items expiring today.")
        else:
            for r in critical[:5]:
                name = r.get("name") or "item"
                typ = r.get("type") or ""
                st.markdown(f"- **{name}** · *{typ}* {_badge('today', '#5b1a1a', '#ffd1d1')}", unsafe_allow_html=True)
            if len(critical) > 5:
                st.caption(f"…and {len(critical)-5} more today.")

    with cols[1]:
        st.markdown("**Soon (1–3 days)**")
        if not urgent:
            st.caption("No near-term risks.")
        else:
            for r in urgent[:5]:
                name = r.get("name") or "item"
                days = r.get("days")
                when = f"in {int(days)}d" if isinstance(days, (int, float)) and days >= 0 else "soon"
                st.markdown(f"- **{name}** · {_badge(when, '#5b3a1a', '#ffe7c2')}", unsafe_allow_html=True)
            if len(urgent) > 5:
                st.caption(f"…and {len(urgent)-5} more in 1–3 days.")

    st.caption("Open the Coach page for actions like freeze, use, or recipe rescue.")

def _render_upcoming_week(rows: List[tuple]) -> None:
    st.subheader("⏳ Expiring this week")
    today = date.today(); horizon = today + timedelta(days=7)
    upcoming: List[Tuple[str, date, str]] = []
    for _, name, exp, typ, qty, unit in rows:
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
    rows = _recent_activity(user_id, limit=5)
    if not rows:
        st.caption("No recent activity yet.")
        return
    for ts, ev, qty, nm in rows:
        emoji = "✅" if ev == "used" else ("⛔" if ev == "expired" else "•")
        qty_txt = f"{qty:g}".rstrip(".")
        st.write(f"{emoji} {ts} — **{nm}** · {ev} · {qty_txt}")

def _render_quick_links() -> None:
    st.subheader("🔗 Quick links")
    cols = st.columns(4)
    cols[0].markdown("**📦 Stock**  \nOpen your inventory.")
    cols[1].markdown("**🛒 Shopping**  \nReview store carts.")
    cols[2].markdown("**🧠 Coach**  \nHandle at-risk items.")
    cols[3].markdown("**📊 Stats**  \nSee the dashboard.")

def _render_calendar(rows: List[tuple]) -> None:
    with st.expander("🗓 Week calendar"):
        if _calendar is None:
            st.info("Calendar widget unavailable. Install `streamlit-calendar` to enable the week view.")
            return
        events = []
        for _, name, exp, typ, qty, unit in rows:
            try:
                if float(qty or 0) <= 0:
                    continue
            except Exception:
                continue
            d = _parse_date(exp)
            events.append({"title": f"{name} ({typ})", "start": d.isoformat(), "end": d.isoformat(), "allDay": True})
        _calendar(options={
            "initialView": "dayGridWeek",
            "height": 420,
            "events": events,
            "headerToolbar": {"left": "", "center": "", "right": ""},
            "dayMaxEvents": True,
        })

# --------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------
def calendar_view() -> None:
    user = _resolve_user()
    if not user:
        st.info("Please log in to see your homepage.")
        return

    user_id = int(user["id"])
    user_name = user.get("name") or "User"
    rows = _inventory_rows(user_id)

    # Header + banner
    _render_header(user_name)

    # Essentials
    _render_notifications(user_id)
    st.divider()
    _render_upcoming_week(rows)
    st.divider()
    _render_activity(user_id)
    st.divider()
    _render_quick_links()
    _render_calendar(rows)

# Compatibility aliases
def render():
    calendar_view()

def app():
    calendar_view()

if __name__ == "__main__":
    calendar_view()
