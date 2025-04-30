import streamlit as st
import sqlite3
import openai
from datetime import datetime

# Load OpenAI API key
openai.api_key = st.secrets.get("OPENAI_API_KEY")

# Common pantry items allowed in flexible mode
PANTRY_ITEMS = ["salt", "sugar", "black pepper", "olive oil", "vegetable oil", "butter", "lemon juice", "baking powder"]

# --- DB connection ---
def get_connection():
    return sqlite3.connect("inventory.db")

def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, expiration, type FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

# --- Main Page ---
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

    # Suggestion Mode
    suggestion_mode = st.radio(
        "Suggestion Mode:",
        [
            "Strict: Only use selected ingredients",
            "Flexible: Allow pantry items and suggest extras"
        ],
        index=1
    )

    if st.button("🍚 Suggest Meal for Selected Items"):
        if not selected_items:
            st.warning("⚠️ Please select at least one item.")
        else:
            selected_str = "\n".join(selected_items)

            if suggestion_mode == "Strict: Only use selected ingredients":
                prompt = (
                    "You are a helpful chef assistant.\n"
                    f"ONLY use the following ingredients:\n{selected_str}\n\n"
                    "Do NOT use any other ingredients.\n"
                    "Suggest one simple recipe using ONLY these.\n"
                    "List exact quantities (grams/ml), clear steps, and estimated total calories."
                )
            else:
                pantry_list = ", ".join(PANTRY_ITEMS)
                prompt = (
                    "You are a helpful chef assistant.\n"
                    f"Main ingredients:\n{selected_str}\n\n"
                    f"You may also use these pantry items if needed: {pantry_list}.\n"
                    "You MAY suggest other helpful ingredients, but clearly label them as '(recommended to buy)'.\n"
                    "List quantities (grams/ml), give clear steps, and estimate total calories."
                )

            with st.spinner("🤔 Thinking..."):
                response = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.6
                )
                result = response.choices[0].message["content"]

                st.session_state["latest_recipe"] = result

                st.success("✅ Recipe Generated!")
                st.markdown(result)

    # --- Proceed Button ---
    if "latest_recipe" in st.session_state:
        st.subheader("✅ Proceed with this Recipe?")
        if st.button("✅ Confirm and Deduct Ingredients"):
            st.info("🚧 Inventory deduction system will be implemented in the next phase!")
cv 