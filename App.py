import streamlit as st
from CalendarView import calendar_view

# --- Set page config ---
st.set_page_config(
    page_title="Smart Inventory Manager",
    page_icon="🍴",
    layout="centered"
)

# --- Import pages after config ---
from home import home
from Inventory import inventory
from AI_Assistant import ai_assistant

# --- Page Mapping ---
PAGES = {
    "🏠 Home": home,
    "📦 Inventory": inventory,
    "🤖 AI Assistant": ai_assistant,
    "📅 Calendar View": calendar_view
}

# --- Top Banner / Branding ---
st.markdown("""
    <div style='background-color:#0B0F2A;padding:15px 25px;border-radius:12px;margin-bottom:20px;'>
        <h1 style='color:#00BFFF;text-align:center;margin:0;'>💡 Smart Inventory</h1>
    </div>
""", unsafe_allow_html=True)

# --- Surprise: Welcome Banner if Logged In ---
if "authenticated" in st.session_state and st.session_state["authenticated"]:
    user = st.session_state.get("phone", "user")
    st.markdown(f"""
    <div style='border: 2px solid #00BFFF; border-radius: 10px; padding: 10px 20px; margin-bottom: 20px; background: linear-gradient(90deg, #0B0F2A, #1A1F3C);'>
        <p style='font-size:16px;color:#00BFFF;'>👋 Welcome back, <b>{user}</b> — let’s manage your food like a pro!</p>
    </div>
    """, unsafe_allow_html=True)

# --- Navigation Bar (Top instead of Sidebar) ---
st.markdown("### 🔍 Navigate")
selection = st.radio("", list(PAGES.keys()), horizontal=True)

# --- Access Control ---
if selection != "🏠 Home":
    if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
        st.warning("⚠️ Please login first from Home page.")
        home()
    else:
        PAGES[selection]()
else:
    PAGES[selection]()
