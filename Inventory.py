import streamlit as st
import sqlite3
from datetime import datetime, date

# --- DB Connection ---
def get_connection():
    return sqlite3.connect("inventory.db")

# --- Add Inventory Item ---
def add_item(user_id, name, expiration, food_type, amount, unit):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO inventory (user_id, name, expiration, type, amount, unit) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, name, expiration, food_type, amount, unit)
    )
    conn.commit()
    conn.close()

# --- Get User Inventory Items ---
def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, expiration, type, amount, unit FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

# --- Delete Expired Items ---
def delete_expired_items(user_id):
    today = date.today().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM inventory WHERE expiration < ? AND user_id = ?", (today, user_id))
    conn.commit()
    conn.close()

# --- Inventory UI Page ---
def inventory():
    st.title("\U0001F4E6 Your Inventory")

    if "user_id" not in st.session_state:
        st.warning("\u26A0\uFE0F Please login first from Home page.")
        st.stop()

    user_id = st.session_state["user_id"]

    # Delete expired items every time page loads
    delete_expired_items(user_id)

    # --- Add Food Form ---
    with st.form("add_food_form"):
        name = st.text_input("Food Name", max_chars=50)
        expiration = st.date_input("Expiration Date", min_value=date.today())
        food_type = st.selectbox("Food Type", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"])
        amount = st.number_input("Amount", min_value=0.01, step=0.01)
        unit = st.selectbox("Unit", ["g", "ml", "pcs"])
        submitted = st.form_submit_button("Add to Inventory")

        if submitted:
            add_item(user_id, name, expiration.strftime("%Y-%m-%d"), food_type, amount, unit)
            st.success(f"✅ {amount} {unit} of {name} added successfully!")

    # --- Display Current Inventory ---
    st.subheader("\U0001F4E6 Current Inventory")
    items = get_user_items(user_id)

    if not items:
        st.info("Inventory is currently empty.")
    else:
        for idx, (name, expiration, food_type, amount, unit) in enumerate(items, start=1):
            exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
            days_left = (exp_date - date.today()).days

            if days_left < 0:
                status = "🔴 Expired"
            elif days_left <= 2:
                status = "🟠 Expiring Soon"
            else:
                status = "🟢 Fresh"

            st.markdown(
                f"**{idx}. {name}** | Type: {food_type} | Amount: {amount} {unit} | Exp: `{expiration}` | {status}"
            )
