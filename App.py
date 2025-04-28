import streamlit as st
from home import home
from Inventory import inventory
from AI_Assistant import ai_assistant

st.set_page_config(page_title="Smart Food Inventory", layout="wide")

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
