import streamlit as st
from datetime import datetime, date
import sqlite3
import openai
from twilio.rest import Client
# This is a sync test to force Git to recognize the change
# SYNC TEST 9 – Confirming file change


# 🔐 API keys via Streamlit secrets
openai.api_key = st.secrets.get("OPENAI_API_KEY", "sk-...")

# --- Database ---
def get_connection():
    return sqlite3.connect("inventory.db")

def add_item(name, expiration, food_type):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO inventory (name, expiration, type) VALUES (?, ?, ?)",
                   (name, expiration, food_type))
    conn.commit()
    conn.close()

def get_all_items():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, expiration, type FROM inventory")
    items = cursor.fetchall()
    conn.close()
    return items

# --- GPT Suggestion ---
def get_ai_suggestion():
    items = get_all_items()
    if not items:
        return "Your inventory is empty."

    inventory_str = "\n".join([
        f"{name} (Type: {food_type}, Expires: {expiration})"
        for name, expiration, food_type in items
    ])

    prompt = (
        "You are a helpful kitchen assistant.\n"
        "Based on the following food inventory, suggest what should be used today to avoid waste, "
        "and recommend basic meal ideas:\n\n"
        f"{inventory_str}\n\n"
        "Suggestions:"
    )

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )

    return response.choices[0].message["content"]

# --- WhatsApp: Expiring Items ---
def get_expiring_items():
    items = get_all_items()
    expiring = []

    for name, expiration, food_type in items:
        exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        days_left = (exp_date - date.today()).days
        if days_left <= 2:
            expiring.append(f"{name} (in {days_left} days)")

    return expiring

def send_whatsapp_reminder():
    expiring = get_expiring_items()
    if not expiring:
        return "✅ Nothing expiring soon."

    message_text = "⚠️ Items expiring soon:\n" + "\n".join(expiring)

    client = Client(
        st.secrets["TWILIO_SID"],
        st.secrets["TWILIO_AUTH_TOKEN"]
    )

    message = client.messages.create(
        from_=st.secrets["WHATSAPP_FROM"],
        body=message_text,
        to=st.secrets["WHATSAPP_TO"]
    )

    return "✅ WhatsApp reminder sent!"

# --- WhatsApp: Full Inventory ---
def send_full_inventory_to_whatsapp():
    items = get_all_items()
    if not items:
        return "📭 Inventory is empty. Nothing to send."

    message = "📋 Current Inventory:\n"
    for name, expiration, food_type in items:
        message += f"- {name} ({food_type}), expiring on {expiration}\n"

    client = Client(
        st.secrets["TWILIO_SID"],
        st.secrets["TWILIO_AUTH_TOKEN"]
    )

    client.messages.create(
        from_=st.secrets["WHATSAPP_FROM"],
        body=message,
        to=st.secrets["WHATSAPP_TO"]
    )

    return "✅ Full inventory sent to WhatsApp."

# --- Streamlit App UI ---
st.title("🥗 Smart Food Inventory")

# Add food form
with st.form("add_food_form"):
    name = st.text_input("Food Name", max_chars=50)
    expiration = st.date_input("Expiration Date", min_value=date.today())
    food_type = st.selectbox("Food Type", ["Dairy", "Fruit", "Meat", "Grain", "Vegetable", "Other"])
    submitted = st.form_submit_button("Add to Inventory")

    if submitted:
        add_item(name, expiration.strftime("%Y-%m-%d"), food_type)
        st.success(f"✅ {name} added successfully!")

# Display inventory
st.subheader("📦 Current Inventory")
items = get_all_items()

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

# AI Suggestions
st.subheader("🤖 AI Suggestions")
if st.button("What should I use today?"):
    with st.spinner("Thinking..."):
        suggestion = get_ai_suggestion()
        st.success("Here's what I recommend:")
        st.write(suggestion)

# WhatsApp Buttons (visible below AI suggestions)
st.subheader("📲 WhatsApp Notifications")

col1, col2 = st.columns(2)

with col1:
    if st.button("Send Expiry Alert"):
        with st.spinner("Sending..."):
            result = send_whatsapp_reminder()
            st.success(result)

with col2:
    if st.button("Send Full Inventory"):
        with st.spinner("Sending full inventory..."):
            result = send_full_inventory_to_whatsapp()
            st.success(result)
