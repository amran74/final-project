# --- Full Updated Inventory Code with Usage Tracking and Stable Items ---
import streamlit as st
import sqlite3
from datetime import datetime, date
from whatsapp_utils import send_whatsapp_message

# --- DB Connection ---
def get_connection():
    return sqlite3.connect("inventory.db")

# --- DB Functions ---
def add_item(user_id, name, expiration, food_type, amount, unit, stable=False):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO inventory 
        (user_id, name, expiration, type, amount, unit, used_count, last_used_month, stable) 
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (user_id, name, expiration, food_type, amount, unit, date.today().strftime("%Y-%m"), int(stable))
    )
    conn.commit()
    conn.close()

def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, expiration, type, amount, unit, used_count, last_used_month, stable 
        FROM inventory 
        WHERE user_id = ?
    """, (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

def delete_expired_items(user_id):
    today = date.today().strftime("%Y-%m-%d")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM inventory WHERE expiration < ? AND user_id = ? AND stable = 0", (today, user_id))
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

def mark_item_used(item_id, user_id):
    conn = get_connection()
    cursor = conn.cursor()

    today = date.today()
    current_month = today.strftime("%Y-%m")
    cursor.execute("SELECT used_count, last_used_month FROM inventory WHERE id = ?", (item_id,))
    used_count, last_month = cursor.fetchone()

    if last_month != current_month:
        used_count = 0  # Reset

    used_count += 1

    cursor.execute("""
        UPDATE inventory 
        SET used_count = ?, last_used_month = ? 
        WHERE id = ?
    """, (used_count, current_month, item_id))

    cursor.execute("""
        INSERT INTO usage_log (user_id, item_id, used_date, used_count)
        VALUES (?, ?, ?, 1)
    """, (user_id, item_id, today.strftime("%Y-%m-%d")))

    conn.commit()
    conn.close()

# --- Inventory UI ---
def inventory():
    st.markdown("<h2 style='text-align:center; color:#FF5A5F;'>\ud83d\udce6 Smart Inventory Manager</h2>", unsafe_allow_html=True)

    if "user_id" not in st.session_state:
        st.warning("\u26a0\ufe0f Please login first from Home page.")
        st.stop()

    user_id = st.session_state["user_id"]
    delete_expired_items(user_id)
    items = get_user_items(user_id)

    # --- Add Form ---
    st.markdown("### \u2795 Add New Item")
    with st.form("add_food_form", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 1, 1])
        name = col1.text_input("Food Name", max_chars=50)
        expiration = col2.date_input("Expiration Date", min_value=date.today())
        food_type = col3.selectbox("Type", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"])
        col4, col5 = st.columns([1, 1])
        amount = col4.number_input("Amount", min_value=0.0, step=1.0)
        unit = col5.selectbox("Unit", ["kg", "liter", "pcs"])
        stable = st.checkbox("\u2696\ufe0f Always Keep in Inventory (Stable Item)")

        if st.form_submit_button("\u2705 Add to Inventory"):
            if not name.strip():
                st.warning("\u26a0\ufe0f Food name is required.")
            else:
                add_item(user_id, name, expiration.strftime("%Y-%m-%d"), food_type, amount, unit, stable)
                st.success(f"\u2705 {amount} {unit} of {name} added!")
                st.rerun()

    # --- Inventory Display ---
    st.markdown("### \ud83d\udccb Your Inventory")
    if not items:
        st.info("\ud83e\udade Inventory is empty.")
    else:
        colA, colB = st.columns(2)
        for idx, (item_id, name, expiration, food_type, amount, unit, used_count, last_month, stable) in enumerate(items):
            col = colA if idx % 2 == 0 else colB
            exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
            days_left = (exp_date - date.today()).days

            if days_left < 0:
                status = "\ud83d\udd34 Expired"
                color = "#FF4B4B"
            elif days_left <= 2:
                status = "\ud83d\dfE0 Expiring Soon"
                color = "#FFA500"
            else:
                status = "\ud83d\udfe2 Fresh"
                color = "#4CAF50"

            with col:
                st.markdown(f"""
                    <div style='background-color:#1f1f1f;border-left:5px solid {color};padding:15px 20px;border-radius:12px;margin-bottom:15px'>
                        <h4 style='margin-bottom:0;color:#FAFAFA'>{name} <span style='font-size:14px;color:#888;'>({food_type})</span></h4>
                        <p style='margin:4px 0;color:#CCC;'>\ud83d\udcc5 <b>Expires:</b> {expiration}</p>
                        <p style='margin:4px 0;color:#CCC;'>\ud83d\udd22 <b>Amount:</b> {amount} {unit}</p>
                        <p style='margin:4px 0;color:#CCC;'>\ud83d\udcc6 <b>Status:</b> <span style='color:{color}'>{status}</span></p>
                        <p style='margin:4px 0;color:#CCC;'>\u2705 <b>Used this month:</b> {used_count}</p>
                        {"<p style='margin:4px 0;color:#0ff;'>\u2696\ufe0f <b>Stable Item</b></p>" if stable else ""}
                    </div>
                """, unsafe_allow_html=True)

                col_btn1, col_btn2 = st.columns(2)

                if col_btn1.button("\ud83d\udcc3 Mark Used", key=f"used_{item_id}"):
                    mark_item_used(item_id, user_id)
                    st.success(f"\u2705 Marked 1 use of {name}.")
                    st.rerun()

                if col_btn2.button("\ud83d\uddd1\ufe0f Delete", key=f"delete_{item_id}"):
                    delete_item(item_id)
                    st.rerun()

    # --- WhatsApp Summary ---
    st.markdown("### \ud83d\udce4 Send Summary to WhatsApp")
    if st.button("\ud83d\udcf2 Send WhatsApp Inventory Summary"):
        try:
            expiring_soon = [name for (_, name, exp, *_rest) in items if (datetime.strptime(exp, "%Y-%m-%d").date() - date.today()).days <= 2]
            msg = f"You currently have {len(items)} items.\nExpiring soon: {', '.join(expiring_soon) if expiring_soon else 'None'}"
            sid = send_whatsapp_message(msg)
            st.success(f"\u2705 WhatsApp message sent! SID: {sid}")
        except Exception as e:
            st.error(f"\u274c Failed to send WhatsApp message: {e}")