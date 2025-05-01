import streamlit as st
import openai
import sqlite3
from datetime import datetime, date
import json

openai.api_key = st.secrets.get("OPENAI_API_KEY")

# --- DB ---
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

def ai_assistant():
    st.title("🤖 AI Meal Assistant")

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please login first from Home page.")
        return

    user_id = st.session_state["user_id"]
    items = get_user_items(user_id)

    if not items:
        st.info("Your inventory is empty. Add some items to get suggestions.")
        return

    # Build inventory string for AI
    inventory_str = "\n".join([
        f"{name} ({amount} {unit})"
        for _, name, _, _, amount, unit in items
    ])

    # --- Prompt AI ---
    if st.button("Generate Recipe Suggestion"):
        with st.spinner("Thinking of a recipe..."):
            prompt = (
                "You are a kitchen assistant. Based on this inventory list, suggest a creative meal to avoid waste."
                " Provide the recipe and ingredients in a JSON list (name, amount, unit).\n"
                f"Inventory:\n{inventory_str}\n\n"
                "Format the response like:\n"
                "---\n"
                "Meal: [meal title]\n"
                "Instructions: [step-by-step instructions]\n"
                "Ingredients: [\n  {\"name\": \"chicken\", \"amount\": 200, \"unit\": \"g\"}, ...\n]"
            )

            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )

            full_text = response.choices[0].message.content

            # Extract sections
            try:
                meal_title = full_text.split("Meal:")[1].split("Instructions:")[0].strip()
                instructions = full_text.split("Instructions:")[1].split("Ingredients:")[0].strip()
                ingredients_block = full_text.split("Ingredients:")[1].strip()
                ingredients_list = json.loads(ingredients_block)
            except Exception as e:
                st.error("Failed to parse recipe. Try again.")
                st.text(full_text)
                return

            # Display recipe
            st.subheader(meal_title)
            st.markdown(f"**Instructions:**\n{instructions}")
            st.markdown("**Ingredients Needed:**")
            for ing in ingredients_list:
                st.markdown(f"- {ing['amount']} {ing['unit']} of {ing['name']}")

            # --- Deduct Button ---
            if st.button("✅ Proceed with This Recipe"):
                deducted = []
                not_found = []

                for ing in ingredients_list:
                    matched = False
                    for item in items:
                        item_id, name, exp, food_type, amount, unit = item
                        if name.lower() == ing["name"].lower() and unit == ing["unit"]:
                            if amount >= ing["amount"]:
                                new_amt = round(amount - ing["amount"], 2)
                                update_item_amount(item_id, new_amt)
                                deducted.append(ing["name"])
                                matched = True
                                break
                            else:
                                not_found.append(f"{ing['name']} (needed {ing['amount']}, have {amount})")
                                matched = True
                                break
                    if not matched:
                        not_found.append(f"{ing['name']} (not in inventory)")

                if deducted:
                    st.success(f"✅ Deducted: {', '.join(deducted)}")
                if not_found:
                    st.warning("⚠️ Issues:\n" + "\n".join(not_found))

                st.rerun()
