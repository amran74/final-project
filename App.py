import streamlit as st
from CalendarView import calendar_view
from home import home
from Inventory import inventory
from AI_Assistant import ai_assistant

# --- Page Config ---
st.set_page_config(
    page_title="Smart Inventory Manager",
    page_icon="🍴",
    layout="centered"
)

# --- Pages when logged in ---
PAGES = {
    "🏡 Home": calendar_view,
    "📦 Inventory": inventory,
    "🤖 AI Assistant": ai_assistant
}

# --- Unauthenticated Users: Login/Register Only ---
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    home()
else:
    # --- Top Branding Banner ---
    st.markdown("""
        <div style='background-color:#0B0F2A;padding:15px 25px;border-radius:12px;margin-bottom:20px;'>
            <h1 style='color:#00BFFF;text-align:center;margin:0;'>💡 Smart Inventory</h1>
        </div>
    """, unsafe_allow_html=True)

    # --- Personalized Welcome Banner ---
    user_name = st.session_state.get("name", st.session_state.get("phone", "user"))
    st.markdown(f"""
        <div style='border: 2px solid #00BFFF; border-radius: 10px; padding: 10px 20px; margin-bottom: 20px; background: linear-gradient(90deg, #0B0F2A, #1A1F3C);'>
            <p style='font-size:16px;color:#00BFFF;'>👋 Welcome back, <b>{user_name}</b></p>
        </div>
    """, unsafe_allow_html=True)

    # --- Top Navigation ---
    st.markdown("### 🔍 Navigate")
    selection = st.radio("", list(PAGES.keys()), horizontal=True)

    # --- Load Selected Page ---
    PAGES[selection]()
