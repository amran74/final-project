import streamlit as st
import sqlite3
from datetime import datetime, date
from whatsapp_utils import send_whatsapp_message  # ✅ NEW

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
    cursor.execute("SELECT id, name, expiration, type, amount, unit FROM inventory WHERE user_id = ?", (user_id,))
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

# --- Delete Single Item ---
def delete_item(item_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

# --- Update Inventory Item ---
def update_item(item_id, name, expiration, food_type, amount, unit):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE inventory SET name = ?, expiration = ?, type = ?, amount = ?, unit = ?
        WHERE id = ?
    """, (name, expiration, food_type, amount, unit, item_id))
    conn.commit()
    conn.close()

# --- Inventory UI Page ---
def inventory():
    st.title("📦 Your Inventory")

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please login first from Home page.")
        st.stop()

    user_id = st.session_state["user_id"]

    # Delete expired items every time page loads
    delete_expired_items(user_id)

    # --- Add Food Form ---
    with st.form("add_food_form"):
        name = st.text_input("Food Name", max_chars=50)
        expiration = st.date_input("Expiration Date", min_value=date.today())
        food_type = st.selectbox("Food Type", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"])
        amount = st.number_input("Amount", min_value=0.1, step=1.0)
        unit = st.selectbox("Unit", ["kg", "liter", "pcs"])
        submitted = st.form_submit_button("Add to Inventory")

        if submitted:
            if not name.strip():
                st.warning("⚠️ Food name is required.")
            else:
                add_item(user_id, name, expiration.strftime("%Y-%m-%d"), food_type, amount, unit)
                st.success(f"✅ {amount} {unit} of {name} added successfully!")
                st.rerun()

    # --- Display Current Inventory ---
    st.subheader("📦 Current Inventory")
    items = get_user_items(user_id)

    if not items:
        st.info("Inventory is currently empty.")
    else:
        for idx, (item_id, name, expiration, food_type, amount, unit) in enumerate(items, start=1):
            exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
            days_left = (exp_date - date.today()).days

            if days_left < 0:
                status = "🔴 Expired"
            elif days_left <= 2:
                status = "🟠 Expiring Soon"
            else:
                status = "🟢 Fresh"

            with st.expander(f"**{idx}. {name}** | {amount} {unit} | {status}"):
                new_name = st.text_input(f"Edit Name {idx}", name, key=f"name{idx}")
                new_exp = st.date_input(f"Edit Expiration {idx}", exp_date, key=f"exp{idx}")
                new_type = st.selectbox(f"Edit Type {idx}", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"], index=["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"].index(food_type), key=f"type{idx}")
                new_amt = st.number_input(f"Edit Amount {idx}", value=amount, step=1.0, key=f"amt{idx}")
                new_unit = st.selectbox(f"Edit Unit {idx}", ["kg", "liter", "pcs"], index=["kg", "liter", "pcs"].index(unit), key=f"unit{idx}")

                col1, col2 = st.columns(2)
                with col1:
                    if st.button(f"💾 Save {idx}"):
                        update_item(item_id, new_name, new_exp.strftime("%Y-%m-%d"), new_type, new_amt, new_unit)
                        st.success("Item updated successfully.")
                        st.rerun()
                with col2:
                    if st.button(f"🗑️ Delete {idx}"):
                        delete_item(item_id)
                        st.warning("Item deleted.")
                        st.rerun()

    # --- WhatsApp Summary ---
    st.subheader("📤 WhatsApp Summary")
    if st.button("Send WhatsApp Inventory Summary"):
        try:
            expiring_soon = [name for (_, name, exp, _, _, _) in items if (datetime.strptime(exp, "%Y-%m-%d").date() - date.today()).days <= 2]
            msg = (
                f"You currently have {len(items)} items.\n"
                f"Expiring soon: {', '.join(expiring_soon) if expiring_soon else 'None'}"
            )
            sid = send_whatsapp_message(msg)
            st.success(f"✅ WhatsApp message sent! SID: {sid}")
        except Exception as e:
            st.error(f"❌ Failed to send WhatsApp message: {e}")
