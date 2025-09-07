# App.py — Smart Inventory Manager (polished UI + compact pill nav)

from datetime import date
import streamlit as st

# ================== Page config ==================
st.set_page_config(
    page_title="Smart Inventory Manager",
    page_icon="🍴",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Pages ---
from CalendarView import calendar_view
from home import home

try:
    from Inventory import inventory
except ModuleNotFoundError:
    from inventory import inventory

# Shopping page (capital/lowercase fallback)
try:
    from Shopping import shopping as shopping_page
except ModuleNotFoundError:
    from shopping import shopping as shopping_page

from AI_Assistant import ai_assistant
from dashboard import dashboard
from SmartCoach import coach

# --- DB helpers ---
from db import create_tables, reset_monthly_counters, get_connection, get_monthly_summary

# ================== Styles ==================
st.markdown("""
<style>
:root{
  --bg:#0a1026; --panel:#0d1330; --panel-2:#0f1637; --stroke:#1a2a52;
  --text:#e8f2ff; --muted:#a8bdd6; --accent:#00bfff; --accent-2:#3b82f6;
}

.stApp{ background: radial-gradient(1200px 600px at 12% 12%, #0e173a, var(--bg)) fixed !important; }
.block-container{ padding-top: 12px !important; padding-bottom: 24px !important; }

/* Sticky header with subtle blur */
.header{
  position: sticky; top: 8px; z-index: 10;
  background: color-mix(in srgb, var(--panel) 88%, transparent);
  -webkit-backdrop-filter: blur(8px); backdrop-filter: blur(8px);
  border:1px solid var(--stroke); border-radius:16px;
  padding:12px 14px; margin-bottom:14px; box-shadow: 0 10px 30px rgba(0,0,0,.25);
}

/* Brand row */
.brand{ display:flex; align-items:center; gap:10px; }
.brand h3{ margin:0; color:var(--text); font-weight:700; letter-spacing:.2px; }
.brand .logout button{
  height:36px !important; padding:0 12px !important; border-radius:10px !important;
  background:#121a3a !important; border:1px solid var(--stroke) !important; color:#dfe9f3 !important;
}
.brand .logout button:hover{ border-color:var(--accent) !important; }

/* KPI cards */
.kpi-wrap{ display:grid; grid-template-columns: repeat(4, minmax(140px,1fr)); gap:10px; }
.kpi{
  background: var(--panel-2);
  border:1px solid var(--stroke); border-radius:14px; padding:10px 12px;
  display:grid; grid-template-columns: 28px 1fr; gap:10px; align-items:center;
}
.kpi .ico{
  width:28px; height:28px; border-radius:8px; display:grid; place-items:center;
  background: linear-gradient(180deg, #18305f, #12264b); color:#bfe7ff; font-size:14px;
}
.kpi .val{ font-weight:800; font-size:20px; color:var(--text); line-height:1; }
.kpi .lbl{ font-size:12px; color:var(--muted); margin-top:2px; }

/* Right area: user + nav */
.rightbox{ display:flex; flex-direction:column; gap:8px; align-items:flex-end; }
.username{ color:#9bd7ff; font-weight:700; }

/* Pills nav – compact, non-cramped */
div[data-testid="column"] > div:has(.navbtn) {
  flex: 0 0 auto !important;
  min-width: 0 !important;
  white-space: nowrap !important;
}
.navrow{ display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }
.navbtn { display:inline-block; }
.navbtn > button{
  min-width: 132px !important;
  max-width: 132px !important;
  height: 36px !important;
  padding: 0 10px !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 6px !important;
  border-radius: 10px !important;
  border: 1px solid var(--stroke) !important;
  background: #121734 !important;
  color: #dfe9f3 !important;
  font-size: 14px !important;
  font-weight: 600 !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  line-height: 1 !important;
}
.navbtn > button * { white-space: nowrap !important; }
.navbtn.active > button{
  background: linear-gradient(180deg,#15345a,#0f2746) !important;
  border-color: var(--accent) !important; color:#eaf6ff !important;
}
.navbtn > button:hover{ border-color: var(--accent) !important; }
.navbtn > button:focus{ outline:none !important; box-shadow:none !important; }

/* Gentle section divider */
hr.section{ border: none; height:1px; background: linear-gradient(90deg, transparent, #2a3f70, transparent); opacity:.35; margin:20px 0 6px; }
</style>
""", unsafe_allow_html=True)

# ================== One-time DB sanity ==================
create_tables()
reset_monthly_counters()

# ================== Page registry ==================
PAGES = {
    "🏡 Home": calendar_view,
    "📦 Stock": inventory,
    "🛒 Shopping": shopping_page,
    "🧠 Coach": coach,
    "🤖 AI": ai_assistant,
    "📊 Stats": dashboard,
}
PAGE_KEYS = list(PAGES.keys())

# URL aliases
ALIAS = {
    "home": "🏡 Home",
    "inventory": "📦 Stock",
    "stock": "📦 Stock",
    "shopping": "🛒 Shopping",
    "coach": "🧠 Coach",
    "ai": "🤖 AI",
    "dashboard": "📊 Stats",
    "stats": "📊 Stats",
}

# ================== Helpers ==================
def _user_name() -> str:
    return st.session_state.get("name") or st.session_state.get("phone") or "User"

def _kpis(user_id: int):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM inventory WHERE user_id=?", (user_id,))
    total_items = c.fetchone()[0] or 0
    ms = get_monthly_summary(user_id)
    conn.close()
    return total_items, ms["used_steps"], ms["expired_steps"], ms["money_lost"]

def _goto(label: str):
    st.session_state["__page"] = label
    st.toast(label.strip("📦🏡🧠🤖📊🛒 "), icon="➡️")

# ================== Global post-login interceptor ==================
if st.session_state.get("just_logged_in"):
    st.session_state["__page"] = "🏡 Home"
    st.session_state.pop("just_logged_in", None)
    st.rerun()

# ================== Auth gate ==================
if not st.session_state.get("authenticated"):
    qp = st.query_params
    want = ""
    try:
        want = qp.get("page", [""])[0].lower()
    except Exception:
        pass
    if want in ALIAS:
        st.session_state["post_login_target"] = ALIAS[want]
    home()
    st.stop()

# ================== Jump handler ==================
if st.session_state.get("jump"):
    nav = st.session_state.pop("nav", None)
    st.session_state.pop("jump", None)
    if nav in ALIAS:
        st.session_state["__page"] = ALIAS[nav]
    st.rerun()

# ================== Initial page selection ==================
if "__page" not in st.session_state:
    target = st.session_state.pop("post_login_target", None)
    if not target:
        qp = st.query_params
        want = ""
        try:
            want = qp.get("page", [""])[0].lower()
        except Exception:
            pass
        target = ALIAS.get(want, "🏡 Home")
    st.session_state["__page"] = target

# ================== Header ==================
with st.container():
    st.markdown("<div class='header'>", unsafe_allow_html=True)
    # removed vertical_alignment=... for compatibility with older Streamlit
    a, b, c = st.columns([2.5, 6, 3.5])

    # Left: brand + logout
    with a:
        st.markdown("<div class='brand'><h3>💡 Smart Inventory</h3></div>", unsafe_allow_html=True)
        left_col, right_col = st.columns(2)
        with left_col:
            if st.button("🏠 Home", key="home_quick"):
                st.session_state["__page"] = "🏡 Home"; st.rerun()
        with right_col:
            if st.button("🔐 Logout", key="logout"):
                for k in ["authenticated", "user_id", "phone", "name", "__page", "post_login_target"]:
                    st.session_state.pop(k, None)
                st.rerun()

    # Middle: KPIs (roomier, icons)
    with b:
        uid = st.session_state.get("user_id")
        items, used, expired, lost = (0, 0, 0, 0.0)
        if uid:
            items, used, expired, lost = _kpis(uid)
        st.markdown(
            f"""
            <div class="kpi-wrap">
              <div class="kpi"><div class="ico">📦</div><div><div class="val">{items}</div><div class="lbl">Items</div></div></div>
              <div class="kpi"><div class="ico">✅</div><div><div class="val">{used}</div><div class="lbl">Used (mo)</div></div></div>
              <div class="kpi"><div class="ico">⛔</div><div><div class="val">{expired}</div><div class="lbl">Expired (mo)</div></div></div>
              <div class="kpi"><div class="ico">₪</div><div><div class="val">{lost:.2f}</div><div class="lbl">Money lost (mo)</div></div></div>
            </div>
            """,
            unsafe_allow_html=True
        )

    # Right: user + pill nav (wraps nicely)
    with c:
        st.markdown(f"<div class='rightbox'><div class='username'>👋 {_user_name()}</div>", unsafe_allow_html=True)
        st.markdown("<div class='navrow'>", unsafe_allow_html=True)
        for i, label in enumerate(PAGE_KEYS):
            active = " active" if st.session_state["__page"] == label else ""
            st.markdown(f"<span class='navbtn{active}'>", unsafe_allow_html=True)
            if st.button(label, key=f"nav_{i}"):
                _goto(label)
            st.markdown("</span>", unsafe_allow_html=True)
        st.markdown("</div></div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ================== Render current page ==================
current = st.session_state["__page"]
PAGES.get(current, calendar_view)()

# ================== Footer ==================
st.markdown("<hr class='section'>", unsafe_allow_html=True)
st.markdown(f"""
<div style="font-size:12px;color:#93a4b4;display:flex;justify-content:space-between;">
  <div>v2.0 • {date.today().isoformat()} • {current}</div>
  <div>Made with Python and questionable life choices.</div>
</div>
""", unsafe_allow_html=True)
