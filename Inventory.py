import streamlit as st
import sqlite3
from datetime import datetime, date

# --- DB Functions ---
def get_connection():
    return sqlite3.connect("inventory.db")

def get_user_inventory(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, expiration, type FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

def add_inventory_item(user_id, name, expiration, food_type):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO inventory (user_id, name, expiration, type) VALUES (?, ?, ?, ?)",
                   (user_id, name, expiration, food_type))
    conn.commit()
    conn.close()

def delete_inventory_item(item_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()

# --- Protect ---
if "user_id" not in st.session_state:
    st.error("⚠️ Please login first from Home page.")
    st.stop()

# --- UI ---
st.title("📦 Your Inventory")

# Add food
st.subheader("➕ Add New Item")
with st.form("add_item_form"):
    name = st.text_input("Food Name", max_chars=50)
    expiration = st.date_input("Expiration Date", min_value=date.today())
    food_type = st.selectbox("Food Type", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"])
    submitted = st.form_submit_button("Add to Inventory")

    if submitted:
        add_inventory_item(st.session_state["user_id"], name, expiration.strftime("%Y-%m-%d"), food_type)
        st.success(f"✅ {name} added successfully!")

# Show inventory
st.subheader("📋 Current Items")
items = get_user_inventory(st.session_state["user_id"])

if not items:
    st.info("Your inventory is empty.")
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

        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown(
                f"**{idx}. {name}** | Type: {food_type} | Exp: `{expiration}` | {status}"
            )
        with col2:
            if st.button("❌ Remove", key=f"remove_{item_id}"):
                delete_inventory_item(item_id)
                st.success(f"Deleted {name}. Please refresh.")
