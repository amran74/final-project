# App.py — Smart Inventory Manager (+ Shopping page, dynamic nav)

from datetime import date
import streamlit as st

# ================== Page config (must come before anything Streamlit) ==================
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
    # Works if the file is named Inventory.py (capital I)
    from Inventory import inventory
except ModuleNotFoundError:
    # Fallback if it's inventory.py (lowercase i)
    from inventory import inventory

# Shopping page (capital/lowercase fallback just like Inventory)
try:
    from Shopping import shopping
except ModuleNotFoundError:
    from shopping import shopping

from AI_Assistant import ai_assistant
from dashboard import dashboard
from SmartCoach import coach

# --- DB helpers ---
from db import create_tables, reset_monthly_counters, get_connection, get_monthly_summary

# ================== Styles (nav no-wrap + compact, consistent pills) ==================
st.markdown("""
<style>
.block-container { padding-top: 1rem; }
.header { background:#0b0f2a; border:1px solid #13203a; border-radius:14px; padding:12px 16px; margin-bottom:12px; }
.kpi { background:#0f1428; border:1px solid #1e2a44; border-radius:12px; padding:10px 8px; text-align:center; }
.kpi .val { font-weight:700; font-size:20px; color:#e8f2ff; }
.kpi .lbl { font-size:12px; color:#9bb3c7; }

/* Prevent nav wrapping */
div[data-testid="column"] > div:has(.navbtn) {
  flex: 0 0 auto !important;
  min-width: 0 !important;
  white-space: nowrap !important;
}
.navbtn { display:inline-block; }
.navbtn > button,
div[data-testid="column"] .navbtn > button {
  min-width: 132px !important;
  max-width: 132px !important;
  height: 42px !important;
  padding: 0 12px !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  gap: 6px !important;
  border-radius: 10px !important;
  border: 1px solid #1e2a44 !important;
  background: #121629 !important;
  color: #dfe9f3 !important;
  font-size: 14px !important;
  font-weight: 500 !important;
  white-space: nowrap !important;
  overflow: hidden !important;
  text-overflow: ellipsis !important;
  line-height: 1 !important;
}
.navbtn > button * { white-space: nowrap !important; }
.navbtn.active > button {
  background: #0d2744 !important;
  border-color: #00bfff !important;
  color: #e8f6ff !important;
}
.navbtn > button:hover { border-color:#00bfff !important; }
.navbtn > button:focus { outline:none !important; box-shadow:none !important; }
</style>
""", unsafe_allow_html=True)

# ================== One-time DB sanity ==================
create_tables()
reset_monthly_counters()

# ================== Page registry (insertion order = nav order) ==================
PAGES = {
    "🏡 Home": calendar_view,
    "📦 Stock": inventory,
    "🛒 Shopping": shopping,     # ← new page
    "🧠 Coach": coach,
    "🤖 AI": ai_assistant,
    "📊 Stats": dashboard,
}
PAGE_KEYS = list(PAGES.keys())

# URL aliases like ?page=shopping
ALIAS = {
    "home": "🏡 Home",
    "inventory": "📦 Stock",
    "stock": "📦 Stock",
    "shopping": "🛒 Shopping",   # ← new alias
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
    a, b, c = st.columns([3, 6, 3], vertical_alignment="center")

    with a:
        st.markdown("### 💡 Smart Inventory")
        if st.button("🔐 Logout", key="logout"):
            for k in ["authenticated", "user_id", "phone", "name", "__page", "post_login_target"]:
                st.session_state.pop(k, None)
            st.rerun()

    with b:
        uid = st.session_state.get("user_id")
        items, used, expired, lost = (0, 0, 0, 0.0)
        if uid:
            items, used, expired, lost = _kpis(uid)
        k1, k2, k3, k4 = st.columns(4)
        with k1: st.markdown(f"<div class='kpi'><div class='val'>{items}</div><div class='lbl'>Items</div></div>", unsafe_allow_html=True)
        with k2: st.markdown(f"<div class='kpi'><div class='val'>{used}</div><div class='lbl'>Used (mo)</div></div>", unsafe_allow_html=True)
        with k3: st.markdown(f"<div class='kpi'><div class='val'>{expired}</div><div class='lbl'>Expired (mo)</div></div>", unsafe_allow_html=True)
        with k4: st.markdown(f"<div class='kpi'><div class='val'>₪{lost:.2f}</div><div class='lbl'>Money lost (mo)</div></div>", unsafe_allow_html=True)

    with c:
        st.markdown(f"<div style='text-align:right;color:#9bd7ff;font-weight:600;'>👋 {_user_name()}</div>", unsafe_allow_html=True)

        # ---- Dynamic nav: 1 button per page key ----
        nav_cols = st.columns(len(PAGE_KEYS))
        for i, label in enumerate(PAGE_KEYS):
            active = " active" if st.session_state["__page"] == label else ""
            with nav_cols[i]:
                st.markdown(f"<div class='navbtn{active}'>", unsafe_allow_html=True)
                if st.button(label, key=f"nav_{i}"):
                    _goto(label)
                st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)

# ================== Render current page ==================
current = st.session_state["__page"]
PAGES.get(current, calendar_view)()

# ================== Footer ==================
st.markdown(f"""
<hr style="opacity:0.15">
<div style="font-size:12px;color:#93a4b4;display:flex;justify-content:space-between;">
  <div>v2.0 • {date.today().isoformat()} • {current}</div>
  <div>Made with Python and questionable life choices.</div>
</div>
""", unsafe_allow_html=True)
