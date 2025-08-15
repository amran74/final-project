# App.py — Sleek shell with fixed-width, no-wrap nav + KPIs + deep links + bulletproof post-login redirect
from datetime import date
import streamlit as st

# --- Pages ---
from CalendarView import calendar_view
from home import home
from Inventory import inventory
from AI_Assistant import ai_assistant
from dashboard import dashboard
from SmartCoach import coach

# --- DB helpers ---
from db import create_tables, reset_monthly_counters, get_connection, get_monthly_summary

# ================== Page config ==================
st.set_page_config(
    page_title="Smart Inventory Manager",
    page_icon="🍴",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ================== Styles ==================
st.markdown("""
<style>
.navbtn > button {
    min-width: 130px !important;
    max-width: 130px !important;
    height: 42px !important;
    display: inline-flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 6px !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    padding: 0 10px !important;
    background: #121629 !important;
    border-radius: 10px !important;
    border: 1px solid #1e2a44 !important;
    color: #dfe9f3 !important;
    white-space: nowrap !important; /* THIS stops wrapping */
    overflow: hidden !important;
    text-overflow: ellipsis !important;
}

/* Active state */
.navbtn.active > button {
    background: #0d2744 !important;
    border-color: #00bfff !important;
    color: #e8f6ff !important;
}

/* Remove weird Streamlit hover shadow */
.navbtn > button:hover {
    border-color: #00bfff !important;
}
</style>
""", unsafe_allow_html=True)



# ================== One-time DB sanity ==================
create_tables()
reset_monthly_counters()

# ================== Page registry ==================
PAGES = {
    "🏡 Home": calendar_view,
    "📦 Inventory": inventory,
    "🧠 Smart Coach": coach,
    "🤖 AI Assistant": ai_assistant,
    "📊 Dashboard": dashboard,
}
PAGE_KEYS = list(PAGES.keys())
ALIAS = {  # deep links: ?page=coach etc.
    "home": "🏡 Home",
    "inventory": "📦 Inventory",
    "coach": "🧠 Smart Coach",
    "ai": "🤖 AI Assistant",
    "dashboard": "📊 Dashboard",
}

# ================== Helpers ==================
def _user_name() -> str:
    return st.session_state.get("name") or st.session_state.get("phone") or "User"

def _kpis(user_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM inventory WHERE user_id=?", (user_id,))
    total_items = c.fetchone()[0] or 0
    ms = get_monthly_summary(user_id)
    conn.close()
    return total_items, ms["used_steps"], ms["expired_steps"], ms["money_lost"]

def _goto(label: str):
    st.session_state["__page"] = label
    st.toast(label.replace("📦","").replace("🏡","").replace("🧠","").replace("🤖","").replace("📊","").strip(), icon="➡️")

# ================== Global post-login interceptor ==================
# If home.py just set the flag, force switch to Home and rerun, no matter what.
if st.session_state.get("just_logged_in"):
    st.session_state["__page"] = "🏡 Home"
    st.session_state.pop("just_logged_in", None)
    st.rerun()

# ================== Auth gate ==================
if not st.session_state.get("authenticated"):
    # remember deep link for after login
    qp = st.query_params
    want = ""
    try:
        want = qp.get("page", [""])[0].lower()
    except Exception:
        pass
    if want in ALIAS:
        st.session_state["post_login_target"] = ALIAS[want]

    # render login/register/recover
    home()
    # when login succeeds, home.py sets `authenticated=True` and `just_logged_in=True`;
    # the global interceptor above will catch it on the next run.
    st.stop()

# ================== Jump handler (from CalendarView quick buttons) ==================
if st.session_state.get("jump"):
    nav = st.session_state.pop("nav", None)
    st.session_state.pop("jump", None)
    if nav == "inventory":
        st.session_state["__page"] = "📦 Inventory"
    elif nav == "ai":
        st.session_state["__page"] = "🤖 AI Assistant"
    elif nav == "dashboard":
        st.session_state["__page"] = "📊 Dashboard"
    elif nav == "home":
        st.session_state["__page"] = "🏡 Home"
    st.rerun()

# ================== Initial page selection (deep link aware) ==================
if "__page" not in st.session_state:
    # 1) honor post-login deep link, else 2) honor URL ?page=..., else 3) default Home
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
        lcol = st.columns(2)
        with lcol[0]:
            # Logout
            if st.button("🔐 Logout", key="logout", use_container_width=False):
                for k in ["authenticated", "user_id", "phone", "name", "__page", "post_login_target"]:
                    st.session_state.pop(k, None)
                st.rerun()

    with b:
        # KPIs
        uid = st.session_state.get("user_id")
        items, used, expired, lost = (0, 0, 0, 0.0)
        if uid:
            items, used, expired, lost = _kpis(uid)
        k1, k2, k3, k4 = st.columns(4)
        with k1: st.markdown(f"<div class='kpi'><div class='val'>{items}</div><div class='lbl'>Items</div></div>", unsafe_allow_html=True)
        with k2: st.markdown(f"<div class='kpi'><div class='val'>{used}</div><div class='lbl'>Used steps (mo)</div></div>", unsafe_allow_html=True)
        with k3: st.markdown(f"<div class='kpi'><div class='val'>{expired}</div><div class='lbl'>Expired steps (mo)</div></div>", unsafe_allow_html=True)
        with k4: st.markdown(f"<div class='kpi'><div class='val'>₪{lost:.2f}</div><div class='lbl'>Money lost (mo)</div></div>", unsafe_allow_html=True)

    with c:
        st.markdown(f"<div style='text-align:right;color:#9bd7ff;font-weight:600;'>👋 {_user_name()}</div>", unsafe_allow_html=True)
        # Fixed-width, no-wrap nav
        n1, n2, n3, n4, n5 = st.columns(5)
        nav_cols = [n1, n2, n3, n4, n5]
        for i, label in enumerate(PAGE_KEYS):
            active = " active" if st.session_state["__page"] == label else ""
            with nav_cols[i]:
                st.markdown(f"<div class='navbtn{active}'>", unsafe_allow_html=True)
                if st.button(label, key=f"nav_{i}", use_container_width=True):
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
  <div>v1.8 • {date.today().isoformat()} • {current}</div>
  <div>Made with Python and questionable life choices.</div>
</div>
""", unsafe_allow_html=True)
