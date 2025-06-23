import streamlit as st
from streamlit_calendar import calendar
import sqlite3
from datetime import datetime, date

def get_connection():
    return sqlite3.connect("inventory.db")

def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, expiration, type FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

def calendar_view():
    st.set_page_config(page_title="Home | Smart Inventory", page_icon="🏡")

    if "user_id" not in st.session_state or "name" not in st.session_state:
        st.warning("⚠️ Please login first.")
        return

    user_id = st.session_state["user_id"]
    user_name = st.session_state.get("name", "User")
    today = date.today()
    items = get_user_items(user_id)

    # --- Welcome Header ---
    st.markdown(f"""
        <div style='border: 2px solid #00BFFF; border-radius: 12px; padding: 15px;
        background: linear-gradient(90deg, #0B0F2A, #1A1F3C); text-align: center; margin-bottom: 25px;'>
            <h2 style='color:#00BFFF;'>👋 Welcome back, <span style='color:#FAFAFA'>{user_name}</span></h2>
            <p style='color:#BBB;'>Here’s your dashboard overview.</p>
        </div>
    """, unsafe_allow_html=True)

    # --- Inventory Summary ---
    total_items = len(items)
    expiring_soon = [item for item in items if 0 <= (datetime.strptime(item[1], "%Y-%m-%d").date() - today).days <= 2]
    expired_items = [item for item in items if (datetime.strptime(item[1], "%Y-%m-%d").date() - today).days < 0]

    st.markdown("### 📊 Inventory Overview")
    st.info(f"📦 Total items: **{total_items}**\n\n🟠 Expiring soon: **{len(expiring_soon)}**\n\n🔴 Expired: **{len(expired_items)}**")

    st.divider()

    # --- Quick Access Buttons ---
    st.markdown("### 📂 Quick Access")
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📦 Go to Inventory"):
            st.session_state["nav"] = "inventory"
            st.session_state["jump"] = True
    with col2:
        if st.button("🤖 Open Assistant"):
            st.session_state["nav"] = "ai"
            st.session_state["jump"] = True
    with col3:
        if st.button("⚙️ Settings / Login"):
            st.session_state["nav"] = "home"
            st.session_state["jump"] = True

    st.divider()

    # --- Collapsible Calendar ---
    st.markdown("### 📅 Expiration Calendar")
    with st.expander("📅 Click to show full calendar"):
        events = []
        for name, expiration, food_type in items:
            try:
                exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
                days_left = (exp_date - today).days

                color = "green"
                if days_left < 0:
                    color = "red"
                elif days_left <= 2:
                    color = "orange"

                events.append({
                    "title": f"{name} ({food_type})",
                    "start": expiration,
                    "end": expiration,
                    "color": color
                })
            except Exception as e:
                st.error(f"❌ Error parsing expiration date for {name}: {expiration}")

        options = {
            "initialView": "dayGridMonth",
            "headerToolbar": {
                "left": "prev,next today",
                "center": "title",
                "right": "dayGridMonth,timeGridWeek"
            }
        }

        calendar(events=events, options=options)

    st.divider()

    # --- Daily Tip ---
    st.markdown("### 💡 Tip of the Day")
    st.info("✅ Use this dashboard daily to stay ahead of food waste and keep your kitchen under control.")
