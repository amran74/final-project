import streamlit as st
from home import home
from Inventory import inventory
from AI_Assistant import ai_assistant

# --- Page Mapping ---
PAGES = {
    "🏠 Home": home,
    "📦 Inventory": inventory,
    "🤖 AI Assistant": ai_assistant
}

# --- Sidebar ---
st.sidebar.title("📋 Navigation")
selection = st.sidebar.radio("Go to:", list(PAGES.keys()))

# --- Display Selected Page ---

# ✅ Force authentication for non-Home pages
if selection != "🏠 Home":
    if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
        st.warning("⚠️ Please login first from Home page.")
        home()  # 👈 show the Home page
    else:
        page = PAGES[selection]
        page()
else:
    page = PAGES[selection]
    page()
