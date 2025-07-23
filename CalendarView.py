import streamlit as st
from streamlit_calendar import calendar
import sqlite3
from datetime import datetime, date
import openai

# --- DB Connection ---
def get_connection():
    return sqlite3.connect("inventory.db")

# --- Get Items ---
def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, expiration, type FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

# --- Generate AI Tip ---
def generate_tip_of_the_day(user_id):
    today = datetime.now().strftime("%Y-%m-%d")

    if st.session_state.get("last_tip_date") == today:
        return st.session_state.get("tip_of_the_day")

    items = get_user_items(user_id)
    if not items:
        tip = "🧊 You have no items. Add some to get smart daily tips!"
    else:
        inventory_summary = "\n".join(
            [f"{name} ({type_}), expires on {expiration}" for name, expiration, type_ in items]
        )
        prompt = (
            f"Here is a user's food inventory:\n{inventory_summary}\n\n"
            "Give ONE short, practical daily tip to help them avoid food waste, save money, or plan meals wisely:"
        )

        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=70,
                temperature=0.6
            )
            tip = response.choices[0].message.content.strip()
        except openai.error.OpenAIError:
            tip = "⚠️ Could not fetch a tip today. Try again later."

    st.session_state["last_tip_date"] = today
    st.session_state["tip_of_the_day"] = tip
    return tip

# --- Main Calendar Page ---
def calendar_view():
    st.set_page_config(page_title="Home | Smart Inventory", page_icon="🏡")

    if "user_id" not in st.session_state or "name" not in st.session_state:
        st.warning("⚠️ Please login first.")
        return

    user_id = st.session_state["user_id"]
    user_name = st.session_state.get("name", "user")
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
    st.info(f"📦 You have **{total_items}** total items.\n\n🟠 **{len(expiring_soon)}** expiring soon.\n\n🔴 **{len(expired_items)}** already expired.")
    st.divider()

    # --- Quick Navigation Buttons ---
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

    # --- Expiration Calendar ---
    st.markdown("### 📅 Expiration Calendar")
    with st.expander("📅 Click to show full calendar", expanded=True):
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
                st.error(f"❌ Skipped broken item: {name} - {expiration}")

        if events:
            options = {
                "initialView": "dayGridMonth",
                "headerToolbar": {
                    "left": "prev,next today",
                    "center": "title",
                    "right": "dayGridMonth,timeGridWeek"
                }
            }
            calendar(events=events, options=options)
        else:
            st.info("🪹 No valid items to display on the calendar.")

    st.divider()

    # --- Daily Tip ---
    st.markdown("### 💡 Tip of the Day")
    tip = generate_tip_of_the_day(user_id)
    st.success(tip)
