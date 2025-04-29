import streamlit as st
from CalendarView import calendar_view

# --- Set page config immediately (must be first Streamlit command) ---
st.set_page_config(
    page_title="Smart Inventory Manager",
    page_icon="🍴",
    layout="centered"
)

# --- Now import other pages AFTER setting config ---
from home import home
from Inventory import inventory
from AI_Assistant import ai_assistant

# --- Page Mapping ---
PAGES = {
    "🏠 Home": home,
    "📦 Inventory": inventory,
    "🤖 AI Assistant": ai_assistant,
    "📅 Calendar View": calendar_view  # ✅ Fixed: added missing comma above
}

# --- Sidebar ---
st.sidebar.title("📋 Navigation")
selection = st.sidebar.radio("Go to:", list(PAGES.keys()))

# --- Page Access Control ---
if selection != "🏠 Home":
    if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
        st.warning("⚠️ Please login first from Home page.")
        home()
    else:
        page = PAGES[selection]
        page()
else:
    page = PAGES[selection]
    page()
