# App.py — Product-grade shell with KPIs, deep links, clean nav
import os
from datetime import date

import streamlit as st

# Pages
from CalendarView import calendar_view
from home import home
from Inventory import inventory
from AI_Assistant import ai_assistant
from dashboard import dashboard
from SmartCoach import coach

# DB utils
from db import create_tables, reset_monthly_counters, get_connection, get_monthly_summary

# ========= Page Config (must be first) =========
st.set_page_config(
    page_title="Smart Inventory Manager",
    page_icon="🍴",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ========= Light styling tweak for a cleaner header =========
st.markdown("""
<style>
/* tighter top padding */
.block-container { padding-top: 1.2rem; }
/* header card */
.header-card {
  background: linear-gradient(90deg, #0B0F2A 0%, #1A1F3C 100%);
  border: 1px solid #0e2a45;
  border-radius: 14px;
  padding: 12px 18px;
  margin-bottom: 12px;
}
/* nav pills */
.nav-pill {
  display: inline-block; padding: 8px 12px; border-radius: 10px;
  background: #121629; border: 1px solid #223; color: #dfe9f3; margin-right: 8px;
  text-decoration: none; font-weight: 600;
}
.nav-pill.active { background: #00BFFF22; border-color: #00BFFF; color: #dff6ff; }
.kpi { text-align:center; background:#111522; border:1px solid #223; border-radius:12px; padding:10px 8px; }
.kpi .value { font-size:20px; font-weight:700; }
.kpi .label { font-size:12px; color:#9bb3c7; }
.profile-chip {
  text-align:right; color:#9bd7ff; font-weight:600;
}
</style>
""", unsafe_allow_html=True)

# ========= One-time DB sanity =========
create_tables()
reset_monthly_counters()

# ========= Helpers =========
PAGES = {
    "🏡 Home": calendar_view,
    "📦 Inventory": inventory,
    "🧠 Smart Coach": coach,
    "🤖 AI Assistant": ai_assistant,
    "📊 Dashboard": dashboard,
}

PAGE_KEYS = list(PAGES.keys())
PAGE_ALIAS = {  # deep-link aliases
    "home": "🏡 Home",
    "inventory": "📦 Inventory",
    "coach": "🧠 Smart Coach",
    "ai": "🤖 AI Assistant",
    "dashboard": "📊 Dashboard",
}

def _get_user_name():
    return st.session_state.get("name") or st.session_state.get("phone") or "User"

def _kpis(user_id: int):
    # Pull quick stats for header bar
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM inventory WHERE user_id=?", (user_id,))
    total_items = c.fetchone()[0] or 0
    # money lost this month and steps
    ms = get_monthly_summary(user_id)
    used_steps = ms["used_steps"]
    expired_steps = ms["expired_steps"]
    money_lost_month = ms["money_lost"]
    conn.close()
    return total_items, used_steps, expired_steps, money_lost_month

def _switch_page(label: str):
    st.session_state["__page"] = label
    # tiny UX flourish so users feel something
    st.toast(f"Navigated to {label}", icon="➡️")

# ========= Auth gate =========
if not st.session_state.get("authenticated"):
    # allow deep links to set a target after login
    qp = st.query_params
    target = qp.get("page", [""])[0].lower() if hasattr(qp, "get") else ""
    if target in PAGE_ALIAS:
        st.session_state["post_login_target"] = PAGE_ALIAS[target]
    home()
    st.stop()

# ========= Handle deep links and stateful nav =========
# 1) deep link on first load
if "__page" not in st.session_state:
    # post-login jump
    target = st.session_state.pop("post_login_target", None)
    if target and target in PAGES:
        st.session_state["__page"] = target
    else:
        # query param ?page=coach etc.
        qp = st.query_params
        target = qp.get("page", [""])[0].lower() if hasattr(qp, "get") else ""
        st.session_state["__page"] = PAGE_ALIAS.get(target, "🏡 Home")

# ========= Header with KPIs + profile =========
user_name = _get_user_name()
user_id = st.session_state.get("user_id")

with st.container():
    st.markdown("<div class='header-card'>", unsafe_allow_html=True)
    h1, h2, h3 = st.columns([4, 5, 3])

    # App title + nav
    with h1:
        st.markdown("### 💡 Smart Inventory", unsafe_allow_html=True)
        # simple logout
        lcol1, lcol2 = st.columns([1,1])
        if lcol1.button("🔐 Logout"):
            for k in ["authenticated", "user_id", "phone", "name", "__page"]:
                st.session_state.pop(k, None)
            st.rerun()
        # Debug: optional DB wipe for dev (kept off by default)
        # if lcol2.button("🧨 Dev: Wipe DB"):
        #     if os.path.exists("inventory.db"): os.remove("inventory.db")
        #     st.toast("DB wiped. Restarting.", icon="🧹"); st.rerun()

    # KPIs
    with h2:
        if user_id:
            items, used, expired, lost = _kpis(user_id)
        else:
            items, used, expired, lost = 0, 0, 0, 0.0
        k1, k2, k3, k4 = st.columns(4)
        with k1: st.markdown(f"<div class='kpi'><div class='value'>{items}</div><div class='label'>Items</div></div>", unsafe_allow_html=True)
        with k2: st.markdown(f"<div class='kpi'><div class='value'>{used}</div><div class='label'>Used steps (mo)</div></div>", unsafe_allow_html=True)
        with k3: st.markdown(f"<div class='kpi'><div class='value'>{expired}</div><div class='label'>Expired steps (mo)</div></div>", unsafe_allow_html=True)
        with k4: st.markdown(f"<div class='kpi'><div class='value'>₪{lost:.2f}</div><div class='label'>Money lost (mo)</div></div>", unsafe_allow_html=True)

    # Profile + quick nav
    with h3:
        st.markdown(f"<div class='profile-chip'>👋 {user_name}</div>", unsafe_allow_html=True)
        # nav pills
        nav_row = st.columns(5)
        labels = PAGE_KEYS
        for i, lab in enumerate(labels):
            active = "active" if st.session_state["__page"] == lab else ""
            if nav_row[i].button(lab, key=f"nav_{i}"):
                _switch_page(lab)

    st.markdown("</div>", unsafe_allow_html=True)

# ========= Render selected page =========
current = st.session_state["__page"]
render_fn = PAGES.get(current, calendar_view)
render_fn()

# ========= Footer =========
st.markdown("""
<hr style="opacity:0.2">
<div style="font-size:12px;color:#93a4b4;display:flex;justify-content:space-between;">
  <div>v1.4 • {} • {}</div>
  <div>Made with questionable life choices and Python.</div>
</div>
""".format(date.today().isoformat(), current), unsafe_allow_html=True)
