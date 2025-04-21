import streamlit as st
from datetime import datetime, date
import sqlite3
import openai

# 🔐 OpenAI API Key
openai.api_key ="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"
# --- Database Functions ---
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

# --- GPT Suggestion Function ---
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

# --- Streamlit App Starts Here ---
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

# GPT button
st.subheader("🤖 AI Suggestions")
if st.button("What should I use today?"):
    with st.spinner("Thinking..."):
        suggestion = get_ai_suggestion()
        st.success("Here's what I recommend:")
        st.write(suggestion)
