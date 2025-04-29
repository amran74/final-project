import streamlit as st
import openai
import sqlite3
from datetime import date

openai.api_key = st.secrets["OPENAI_API_KEY"]

def get_connection():
    return sqlite3.connect("inventory.db")

def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, expiration, type FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

def get_ai_suggestion(user_id):
    items = get_user_items(user_id)
    if not items:
        return "Your inventory is empty."

    inventory_str = "\n".join([f"{name} (Type: {food_type}, Expires: {expiration})"
                               for name, expiration, food_type in items])

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

def ai_assistant():
    st.title("🤖 AI Assistant")

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please login first from Home page.")
        st.stop()

    user_id = st.session_state["user_id"]

    if st.button("What should I use today?"):
        with st.spinner("Thinking..."):
            suggestion = get_ai_suggestion(user_id)
            st.success("Here's what I recommend:")
            st.write(suggestion)

if st.button("Suggest Meal for Selected Items"):
    if not selected:
        st.warning("Please select at least one item.")
    else:
        selected_str = "\n".join(selected)
        prompt = (
            "You are a professional chef assistant.\n"
            f"Based on these ingredients:\n{selected_str}\n\n"
            "- Suggest one meal idea.\n"
            "- List **exact quantities** of each ingredient (in grams, ml, pieces).\n"
            "- Give **simple preparation instructions**.\n"
            "- **Estimate total calories** for the entire meal.\n"
            "- Format output as:\n\n"
            "Ingredients:\n- X grams of Y\n- Z ml of W\n\n"
            "Instructions:\n1. Step 1\n2. Step 2\n\n"
            "Estimated Calories: XXXX kcal"
        )

        with st.spinner("Generating..."):
            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6
            )
            recipe_response = response.choices[0].message["content"]
            st.session_state["latest_recipe"] = recipe_response

            st.success("✅ Here's a recipe suggestion:")
            st.write(recipe_response)

            # Show "Proceed" button
            if st.button("✅ Proceed and update inventory"):
                st.info("🔨 Inventory deduction system will be built in next step!")
