import streamlit as st
import sqlite3
from datetime import datetime, date
from db import get_connection, update_item

# --- Add Food Item ---
def add_item(user_id, name, expiration, food_type):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO inventory (user_id, name, expiration, type) VALUES (?, ?, ?, ?)",
                   (user_id, name, expiration, food_type))
    conn.commit()
    conn.close()

# --- Get Items For User ---
def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, expiration, type FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

# --- Main Inventory Page ---
def inventory():
    st.title("📦 Your Inventory")

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please login first from Home page.")
        st.stop()

    user_id = st.session_state["user_id"]

    # --- Add New Item Form ---
    with st.form("add_food_form"):
        name = st.text_input("Food Name", max_chars=50)
        expiration = st.date_input("Expiration Date", min_value=date.today())
        food_type = st.selectbox("Food Type", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"])
        submitted = st.form_submit_button("Add to Inventory")

        if submitted:
            add_item(user_id, name, expiration.strftime("%Y-%m-%d"), food_type)
            st.success(f"✅ {name} added successfully!")
            st.experimental_rerun()

    # --- Show Current Inventory ---
    st.subheader("📋 Current Inventory")
    items = get_user_items(user_id)

    if not items:
        st.info("Inventory is currently empty.")
    else:
        for idx, (item_id, name, expiration, food_type) in enumerate(items, start=1):
            exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
            days_left = (exp_date - date.today()).days

            if days_left < 0:
                status = "🔴 Expired"
            elif days_left <= 2:
                status = "🟠 Expiring Soon"
            else:
                status = "🟢 Fresh"

            with st.expander(f"**{idx}. {name}** | Type: {food_type} | Exp: `{expiration}` | {status}"):
                # Editable fields
                new_name = st.text_input(f"Edit Name {idx}", value=name, key=f"edit_name_{idx}")
                new_type = st.selectbox(f"Edit Type {idx}", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"],
                                        index=["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"].index(food_type),
                                        key=f"edit_type_{idx}")
                new_expiration = st.date_input(f"Edit Expiration {idx}", value=exp_date, key=f"edit_exp_{idx}")

                if st.button(f"💾 Save Changes for {idx}"):
                    update_item(item_id, new_name, new_expiration.strftime("%Y-%m-%d"), new_type)
                    st.success(f"✅ {new_name} updated successfully!")
                    st.experimental_rerun()
