import streamlit as st
import sqlite3
import openai
from datetime import datetime

# Load OpenAI API key
openai.api_key = st.secrets.get("OPENAI_API_KEY")

def get_connection():
    return sqlite3.connect("inventory.db")

def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, expiration, type FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

def ai_assistant():
    st.title("🤖 Smart AI Assistant")

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please login first.")
        return

    user_id = st.session_state["user_id"]
    items = get_user_items(user_id)

    if not items:
        st.info("📭 Your inventory is empty.")
        return

    item_names = [f"{name} ({type})" for name, _, type in items]

    st.subheader("🍳 Create a Meal from Your Inventory")

    selected_items = st.multiselect("Select ingredients:", item_names)

    if st.button("Suggest Meal for Selected Items"):
        if not selected_items:
            st.warning("⚠️ Please select at least one item.")
        else:
            selected_str = "\n".join(selected_items)
            prompt = (
                "You are a helpful chef assistant.\n"
                f"Based on these ingredients:\n{selected_str}\n\n"
                "- Suggest one simple meal idea.\n"
                "- List exact quantities for each ingredient (grams, ml, pieces).\n"
                "- Give simple preparation instructions.\n"
                "- Estimate total calories for the full meal.\n"
                "- Format output like:\n"
                "Ingredients:\n- Xg of Y\n\nInstructions:\n1. Step 1\n2. Step 2\n\nEstimated Calories: XXXX kcal"
            )

            with st.spinner("🤔 Thinking..."):
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.6
                )
                result = response.choices[0].message["content"]

                # Save result temporarily
                st.session_state["latest_recipe"] = result

                st.success("✅ Recipe Generated!")
                st.markdown(result)

    # --- If a recipe is generated, show Proceed Button ---
    if "latest_recipe" in st.session_state:
        st.subheader("✅ Proceed with this Recipe?")

        if st.button("✅ Confirm and Deduct Ingredients"):
            st.info("🚧 Inventory deduction feature will be built in the next step!")
