import streamlit as st
from CalendarView import calendar_view
from home import home
from Inventory import inventory
from AI_Assistant import ai_assistant
from dashboard import dashboard  # ✅ Don't forget this line
from db import reset_monthly_counters
reset_monthly_counters()


# --- Page Config ---
st.set_page_config(
    page_title="Smart Inventory Manager",
    page_icon="🍴",
    layout="centered"
)

# --- Page Mapping ---
PAGES = {
    "🏡 Home": calendar_view,
    "📦 Inventory": inventory,
    "🤖 AI Assistant": ai_assistant,
    "📊 Dashboard": dashboard  # ✅ Make sure it's registered here
}

# --- Login First ---
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    home()
    st.stop()

# --- Handle Redirect Flags ---
if st.session_state.get("jump"):
    st.session_state.pop("jump")
    target = st.session_state.pop("nav", None)
    if target == "inventory":
        inventory()
    elif target == "ai":
        ai_assistant()
    elif target == "home":
        calendar_view()
    elif target == "dashboard":  # ✅ Needed for button navigation
        dashboard()
    st.stop()

# --- Branding Header ---
st.markdown("""
    <div style='background-color:#0B0F2A;padding:15px 25px;border-radius:12px;margin-bottom:20px;'>
        <h1 style='color:#00BFFF;text-align:center;margin:0;'>💡 Smart Inventory</h1>
    </div>
""", unsafe_allow_html=True)

# --- Welcome Message ---
user_name = st.session_state.get("name", st.session_state.get("phone", "User"))
st.markdown(f"""
    <div style='border: 2px solid #00BFFF; border-radius: 10px; padding: 10px 20px; margin-bottom: 20px; background: linear-gradient(90deg, #0B0F2A, #1A1F3C);'>
        <p style='font-size:16px;color:#00BFFF;'>👋 Welcome back, <b>{user_name}</b></p>
    </div>
""", unsafe_allow_html=True)

# --- Navigation Bar ---
st.markdown("### 🔍 Navigate")
selection = st.radio("", list(PAGES.keys()), horizontal=True)

# --- Load Selected Page ---
PAGES[selection]()
