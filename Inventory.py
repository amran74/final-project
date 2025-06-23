import streamlit as st
import sqlite3
from datetime import datetime, date
from whatsapp_utils import send_whatsapp_message

# --- DB Connection ---
def get_connection():
    return sqlite3.connect("inventory.db")

# --- DB Functions ---
def add_item(user_id, name, expiration, food_type, amount, unit):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO inventory (user_id, name, expiration, type, amount, unit) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, name, expiration, food_type, amount, unit)
    )
    conn.commit()
    conn.close()

def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, expiration, type, amount, unit FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

def delete_expired_items(user_id):
    today = date.today().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM inventory WHERE expiration < ? AND user_id = ?", (today, user_id))
    conn.commit()
    conn.close()

def delete_item(item_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

def update_item(item_id, name, expiration, food_type, amount, unit):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE inventory SET name = ?, expiration = ?, type = ?, amount = ?, unit = ?
        WHERE id = ?
    """, (name, expiration, food_type, amount, unit, item_id))
    conn.commit()
    conn.close()

# --- Inventory Page ---
def inventory():
    st.markdown("<h2 style='text-align:center; color:#FF5A5F;'>📦 Smart Inventory Manager</h2>", unsafe_allow_html=True)

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please login first from Home page.")
        st.stop()

    user_id = st.session_state["user_id"]
    delete_expired_items(user_id)
    items = get_user_items(user_id)

    # --- Add Item Form ---
    st.markdown("### ➕ Add New Item")
    with st.form("add_food_form", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 1, 1])
        name = col1.text_input("Food Name", max_chars=50)
        expiration = col2.date_input("Expiration Date", min_value=date.today())
        food_type = col3.selectbox("Type", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"])

        col4, col5 = st.columns([1, 1])
        amount = col4.number_input("Amount", min_value=0.1, step=1.0)
        unit = col5.selectbox("Unit", ["kg", "liter", "pcs"])

        submitted = st.form_submit_button("✅ Add to Inventory")
        if submitted:
            if not name.strip():
                st.warning("⚠️ Food name is required.")
            else:
                add_item(user_id, name, expiration.strftime("%Y-%m-%d"), food_type, amount, unit)
                st.success(f"✅ {amount} {unit} of {name} added!")
                st.rerun()

    # --- Inventory Display ---
    st.markdown("### 📋 Your Inventory")
    if not items:
        st.info("🪹 Your inventory is empty.")
    else:
        colA, colB = st.columns(2)
        for idx, (item_id, name, expiration, food_type, amount, unit) in enumerate(items):
            col = colA if idx % 2 == 0 else colB
            exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
            days_left = (exp_date - date.today()).days

            if days_left < 0:
                status = "🔴 Expired"
                color = "#FF4B4B"
            elif days_left <= 2:
                status = "🟠 Expiring Soon"
                color = "#FFA500"
            else:
                status = "🟢 Fresh"
                color = "#4CAF50"

            with col:
                with st.container():
                    st.markdown(f"""
                    <div style='background-color:#1f1f1f;border-left:5px solid {color};padding:15px 20px;border-radius:12px;margin-bottom:15px'>
                        <h4 style='margin-bottom:0;color:#FAFAFA'>{name} <span style='font-size:14px;color:#888;'>({food_type})</span></h4>
                        <p style='margin:4px 0;color:#CCC;'>📅 <b>Expires:</b> {expiration}</p>
                        <p style='margin:4px 0;color:#CCC;'>🔢 <b>Amount:</b> {amount} {unit}</p>
                        <p style='margin:4px 0;color:#CCC;'>📌 <b>Status:</b> <span style='color:{color}'>{status}</span></p>
                    </div>
                    """, unsafe_allow_html=True)

                    btn1, btn2, btn3 = st.columns([1, 1, 1])

                    # ➕ Quick Add
                    if btn1.button("➕", key=f"plus_{item_id}"):
                        increment = 1.0 if unit == "pcs" else 0.1
                        new_amount = round(amount + increment, 2)
                        update_item(item_id, name, expiration, food_type, new_amount, unit)
                        st.success(f"Added {increment} {unit} to {name}")
                        st.rerun()

                    # ✏️ Edit Form
                    if btn2.button("✏️ Edit", key=f"edit_{item_id}"):
                        with st.form(f"edit_form_{item_id}"):
                            new_name = st.text_input("Name", value=name)
                            new_exp = st.date_input("Expiration", value=exp_date)
                            new_type = st.selectbox("Type", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"],
                                                    index=["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"].index(food_type))
                            new_amt = st.number_input("Amount", value=amount)
                            new_unit = st.selectbox("Unit", ["kg", "liter", "pcs"], index=["kg", "liter", "pcs"].index(unit))
                            if st.form_submit_button("💾 Save Changes"):
                                update_item(item_id, new_name, new_exp.strftime("%Y-%m-%d"), new_type, new_amt, new_unit)
                                st.success("✅ Item updated.")
                                st.rerun()

                    # 🗑️ Delete
                    if btn3.button("🗑️ Delete", key=f"delete_{item_id}"):
                        delete_item(item_id)
                        st.warning("🗑️ Item deleted.")
                        st.rerun()

    # --- WhatsApp Summary ---
    st.markdown("### 📤 Send Summary to WhatsApp")
    if st.button("📲 Send WhatsApp Inventory Summary"):
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
