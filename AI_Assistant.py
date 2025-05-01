import streamlit as st
import sqlite3
import openai
from datetime import datetime
import json
import re

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
    cursor.execute("SELECT id, name, expiration, type, amount, unit FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

def update_item_amount(item_id, new_amount):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE inventory SET amount = ? WHERE id = ?", (new_amount, item_id))
    conn.commit()
    conn.close()

# --- Main Page ---
def ai_assistant():
    st.title("🤖 Smart AI Assistant")

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please login first.")
        return

    user_id = st.session_state["user_id"]
    items = get_user_items(user_id)

    if not items:
        st.info("📬 Your inventory is empty.")
        return

    item_names = [f"{name} ({type})" for _, name, _, type, _, _ in items]

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
            pantry_list = ", ".join(PANTRY_ITEMS)

            if suggestion_mode == "Strict: Only use selected ingredients":
                prompt = (
                    "You are a helpful chef assistant.\n"
                    f"ONLY use the following ingredients:\n{selected_str}\n\n"
                    "Use only these ingredients \u2014 no others allowed.\n"
                    "List exact quantities using 'kg', 'liter', or 'pcs'.\n"
                    "Then list recipe steps clearly.\n"
                    "Estimate total calories.\n"
                    "Format ingredients in JSON and wrap with triple backticks under 'Ingredients:'."
                )
            else:
                prompt = (
                    "You are a helpful chef assistant.\n"
                    f"Use these main ingredients:\n{selected_str}\n\n"
                    f"You may also use pantry items if needed: {pantry_list}.\n"
                    "You MAY suggest helpful extras, but label them as '(recommended to buy)'.\n"
                    "List exact quantities using 'kg', 'liter', or 'pcs'.\n"
                    "List the instructions clearly, and estimate total calories.\n"
                    "Wrap the ingredient JSON list with triple backticks under 'Ingredients:'."
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
            try:
                # Try to extract JSON from triple backticks
                match = re.search(r"```json\s*(\[.*?\])\s*```", st.session_state["latest_recipe"], re.DOTALL)
                if match:
                    ingredients_str = match.group(1)
                else:
                    # Fallback: try extracting list after 'Ingredients:'
                    fallback = st.session_state["latest_recipe"].split("Ingredients:")[-1].strip()
                    ingredients_str = fallback.split("\n")[0] if fallback.startswith("[") else None
                ingredients_json = json.loads(ingredients_str)
            except Exception as e:
                st.warning("\u26a0\ufe0f Could not parse ingredients. Skipping deduction.")
                st.text(f"Error: {e}")
                return

            deducted = []
            missing = []
            for ing in ingredients_json:
                found = False
                for item in items:
                    item_id, name, _, _, amount, unit = item
                    if name.lower() == ing["name"].lower() and unit == ing["unit"]:
                        if amount >= ing["amount"]:
                            new_amount = round(amount - ing["amount"], 2)
                            update_item_amount(item_id, new_amount)
                            deducted.append(ing["name"])
                        else:
                            missing.append(f"{ing['name']} (have {amount}, need {ing['amount']})")
                        found = True
                        break
                if not found:
                    missing.append(f"{ing['name']} (not found)")

            if deducted:
                st.success(f"✅ Deducted: {', '.join(deducted)}")
            if missing:
                st.warning("⚠️ Missing or insufficient: " + ", ".join(missing))

            st.rerun()
