import streamlit as st
import sqlite3
from datetime import datetime, date

# --- DB Connection ---
def get_connection():
    return sqlite3.connect("inventory.db")

# --- Fetch Inventory Stats ---
def get_inventory_stats(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT expiration FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()

    today = date.today()
    total = len(items)
    used = st.session_state.get("used_items", 0)  # Future: move to table
    wasted = len([exp for (exp,) in items if datetime.strptime(exp, "%Y-%m-%d").date() < today])

    return total, used, wasted

# --- Main Dashboard Page ---
def dashboard():
    st.set_page_config(page_title="Dashboard | Smart Inventory", page_icon="📊")
    st.title("📊 Smart Inventory Dashboard")

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please log in first.")
        return

    user_id = st.session_state["user_id"]
    total, used, wasted = get_inventory_stats(user_id)

    # --- KPI Section ---
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("🧺 Total Items Logged", total)
    with col2:
        st.metric("✅ Consumed (Used)", used)
    with col3:
        st.metric("⚠️ Wasted (Expired)", wasted)

    st.divider()

    # --- Placeholder Weekly Chart ---
    st.markdown("### 📈 Weekly Activity Overview")
    st.line_chart({
        "Used": [1, 2, 3, 2, 4, 3, 5],
        "Wasted": [0, 1, 0, 2, 0, 1, 0]
    })

    st.divider()


    # --- Category Breakdown (Future Feature) ---
    st.markdown("### 📦 Category Breakdown")
    st.text("(Coming soon: Pie chart of items used vs wasted per category)")

    # --- Cost Tracking (Future Feature) ---
    st.markdown("### 💸 Cost Tracking")
    st.text("(Coming soon: Total value consumed vs wasted if prices are tracked)")
