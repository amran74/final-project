import streamlit as st
import sqlite3
import openai
from datetime import datetime, date

def ai_assistant():
    st.set_page_config(page_title="AI Suggestions", page_icon="🤖")

    # --- Protect: Must be logged in ---
    if "user_id" not in st.session_state:
        st.error("⚠️ Please login first from Home page.")
        st.stop()

    # --- Database Connection ---
    def get_connection():
        return sqlite3.connect("inventory.db")

    def get_user_inventory(user_id):
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT name, expiration, type FROM inventory WHERE user_id = ?", (user_id,))
        items = cursor.fetchall()
        conn.close()
        return items

    # --- OpenAI Setup ---
    openai.api_key = st.secrets.get("OPENAI_API_KEY", "sk-...")

    # --- UI ---
    st.title("🤖 AI Food Suggestions")

    items = get_user_inventory(st.session_state["user_id"])

    if not items:
        st.info("🧺 Your inventory is empty. Add some food first!")
    else:
        inventory_str = "\n".join([
            f"{name} (Type: {food_type}, Expires: {expiration})"
            for name, expiration, food_type in items
        ])

        prompt = (
            "You are a smart kitchen assistant.\n"
            "Based on the following inventory, suggest what food the user should prioritize using today to avoid waste.\n"
            "Also suggest easy meals or recipes.\n\n"
            f"{inventory_str}\n\n"
            "Suggestions:"
        )

        if st.button("💡 Get Suggestions"):
            with st.spinner("Thinking..."):
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7
                )
                suggestion = response.choices[0].message["content"]
                st.success("Here's what I recommend:")
                st.write(suggestion)
