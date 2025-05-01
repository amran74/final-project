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
                    f"You may also use pantry items if needed: {pantry_list}.\n"
                    "Use only these ingredients — no others allowed other than basic pantry items.\n"
                    "List exact quantities using 'kg', 'liter', or 'pcs' and make sure the amount is suitable for a single person.\n"
                    "Then list recipe steps clearly.\n"
                    "Estimate total calories.\n"
                    "Format the ingredient list in JSON, wrapped with triple backticks like this: ```json [{\"name\": \"rice\", \"amount\": 0.2, \"unit\": \"kg\"}, ...] ```"
                )
            else:
                prompt = (
                    "You are a helpful chef assistant.\n"
                    f"Use these main ingredients:\n{selected_str}\n\n"
                    f"You may also use pantry items if needed: {pantry_list}.\n"
                    "You MAY suggest helpful extras, but label them as '(recommended to buy)'.\n"
                    "List exact quantities using 'kg', 'liter', or 'pcs'.\n"
                    "List the instructions clearly, and estimate total calories.\n"
                    "Format the ingredient list in JSON, wrapped with triple backticks like this: ```json [{\"name\": \"rice\", \"amount\": 0.2, \"unit\": \"kg\"}, ...] ```"
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

                # Clean display of Ingredient List
                match = re.search(r"```json\\s*(\[.*?\])\\s*```", result, re.DOTALL)
                if match:
                    try:
                        ingredients_json = json.loads(match.group(1))
                        st.session_state["deduct_ingredients"] = ingredients_json

                        st.subheader("🧾 Ingredient List:")
                        for ing in ingredients_json:
                            label = ing["name"]
                            if "recommended to buy" in label.lower():
                                label = label.split(":", 1)[-1].strip()
                                st.markdown(f"- 🛒 *{ing['amount']} {ing['unit']} {label}*")
                            else:
                                st.markdown(f"- {ing['amount']} {ing['unit']} {label}")
                    except:
                        pass

                st.markdown(result.split("```json")[0])

    # --- Proceed Button ---
    if "latest_recipe" in st.session_state and suggestion_mode == "Strict: Only use selected ingredients":
        st.subheader("✅ Proceed with this Recipe?")
        if st.button("✅ Confirm and Deduct Ingredients"):
            try:
                ingredients_json = st.session_state.get("deduct_ingredients")
                if not ingredients_json:
                    raise ValueError("No parsed ingredients in session.")
            except Exception as e:
                st.warning("⚠️ Could not parse ingredients. Skipping deduction.")
                st.text(f"Error: {e}")
                return

            deducted = []
            missing = []
            inventory_map = {
                name.lower(): (item_id, amount, unit)
                for item_id, name, _, _, amount, unit in items
            }

            for ing in ingredients_json:
                ing_name = ing["name"].lower()
                ing_amount = ing["amount"]
                ing_unit = ing["unit"]
                if ing_name in inventory_map:
                    item_id, current_amount, current_unit = inventory_map[ing_name]
                    if ing_unit == current_unit:
                        if current_amount >= ing_amount:
                            update_item_amount(item_id, round(current_amount - ing_amount, 2))
                            deducted.append(ing_name)
                        else:
                            missing.append(f"{ing_name} (have {current_amount}, need {ing_amount})")
                    else:
                        missing.append(f"{ing_name} (unit mismatch: {current_unit} vs {ing_unit})")
                else:
                    if ing_name not in [p.lower() for p in PANTRY_ITEMS]:
                        missing.append(f"{ing_name} (not found)")

            if deducted:
                st.success(f"✅ Deducted: {', '.join(deducted)}")
            if missing:
                st.warning("⚠️ Missing or insufficient: " + ", ".join(missing))

            st.rerun()
