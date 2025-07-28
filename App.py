import streamlit as st
from CalendarView import calendar_view
from home import home
from Inventory import inventory
from AI_Assistant import ai_assistant
from dashboard import dashboard
from db import create_tables, reset_monthly_counters
import os

# --- [Optional] DEBUG MODE: Reset DB (Only for Dev Purposes) ---
DEBUG_RESET_DB = False  # Set True temporarily to wipe DB
if DEBUG_RESET_DB and os.path.exists("inventory.db"):
    os.remove("inventory.db")
    print("✅ Deleted old inventory.db for rebuild")

# --- Ensure DB Schema Exists ---
create_tables()
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
    "📊 Dashboard": dashboard
}

# --- Auth Gate ---
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    home()
    st.stop()

# --- Navigation Jump Handling ---
if st.session_state.get("jump"):
    st.session_state.pop("jump")
    target = st.session_state.pop("nav", None)
    if target == "inventory":
        inventory()
    elif target == "ai":
        ai_assistant()
    elif target == "home":
        calendar_view()
    elif target == "dashboard":
        dashboard()
    st.stop()

# --- UI Header ---
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

# --- Navigation ---
st.markdown("### 🔍 Navigate")
selection = st.radio("", list(PAGES.keys()), horizontal=True)

# --- Load Page ---
PAGES[selection]()
