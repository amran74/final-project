import streamlit as st
import sqlite3
from datetime import datetime, date

def get_connection():
    return sqlite3.connect("inventory.db")

def add_item(user_id, name, expiration, food_type):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO inventory (user_id, name, expiration, type) VALUES (?, ?, ?, ?)",
                   (user_id, name, expiration, food_type))
    conn.commit()
    conn.close()

def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, expiration, type FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

def inventory():
    st.set_page_config(page_title="Inventory | Smart Inventory", page_icon="📦")
    st.title("📦 Your Inventory")

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please login first from Home page.")
        st.stop()

    user_id = st.session_state["user_id"]

    # Add food form
    with st.form("add_food_form"):
        name = st.text_input("Food Name", max_chars=50)
        expiration = st.date_input("Expiration Date", min_value=date.today())
        food_type = st.selectbox("Food Type", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"])
        submitted = st.form_submit_button("Add to Inventory")

        if submitted:
            add_item(user_id, name, expiration.strftime("%Y-%m-%d"), food_type)
            st.success(f"✅ {name} added successfully!")

    # Display inventory
    st.subheader("📦 Current Inventory")
    items = get_user_items(user_id)

    if not items:
        st.info("Inventory is currently empty.")
    else:
        for idx, (name, expiration, food_type) in enumerate(items, start=1):
            exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
            days_left = (exp_date - date.today()).days

            if days_left < 0:
                status = "🔴 Expired"
            elif days_left <= 2:
                status = "🟠 Expiring Soon"
            else:
                status = "🟢 Fresh"

            st.markdown(
                f"**{idx}. {name}** | Type: {food_type} | Exp: `{expiration}` | {status}"
            )
