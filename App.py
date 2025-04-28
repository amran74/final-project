import streamlit as st
from Home import home
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
page = PAGES[selection]
page()
