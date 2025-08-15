# AI_Assistant.py — Next-Level AI Cooking & Inventory Brain
import streamlit as st
import openai
from db import get_connection, use_item, expire_item, update_item
from datetime import date

# ======================
# CONFIG
# ======================
MODEL = "gpt-4.1"  # best balance for reasoning + structured output
openai.api_key = st.secrets.get("OPENAI_API_KEY", "")

# ======================
# HELPERS
# ======================
def _get_inventory(user_id):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT id, name, amount, unit, stable, expiration, price_per_unit
        FROM inventory WHERE user_id=?
    """, (user_id,))
    items = c.fetchall()
    conn.close()
    return [
        {"id": i[0], "name": i[1], "amount": i[2], "unit": i[3],
         "stable": bool(i[4]), "expiration": i[5], "price": i[6]}
        for i in items
    ]

def _ai_complete(prompt, sys_prompt="You are a helpful cooking and inventory assistant."):
    resp = openai.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": prompt}
        ],
        temperature=0.7
    )
    return resp.choices[0].message.content.strip()

def _add_item(user_id, name, amount=1, unit="pcs", price=0.0, stable=0):
    conn = get_connection()
    c = conn.cursor()
    c.execute("""
        INSERT INTO inventory (user_id, name, amount, unit, price_per_unit, stable, expiration)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, name, amount, unit, price, stable, date.today().isoformat()))
    conn.commit()
    conn.close()

# ======================
# PAGE
# ======================
def ai_assistant():
    st.title("🤖 AI Cooking & Pantry Assistant")

    if "user_id" not in st.session_state:
        st.error("Please login first.")
        st.stop()

    user_id = st.session_state["user_id"]
    inventory = _get_inventory(user_id)

    tabs = st.tabs(["🍲 AI Recipe Maker", "💡 AI Waste & Cost Insights"])

    # ==================================
    # TAB 1 — Recipe Maker
    # ==================================
    with tabs[0]:
        st.subheader("Smart Pantry Recipe Generator")

        mode = st.radio("Use items from:", ["All Items", "Only Pantry (stable=1)", "Custom Selection"], horizontal=True)

        if mode == "All Items":
            chosen_items = inventory
        elif mode == "Only Pantry (stable=1)":
            chosen_items = [i for i in inventory if i["stable"]]
        else:
            names = [f"{i['name']} ({i['amount']} {i['unit']})" for i in inventory]
            selected = st.multiselect("Select items to include:", names)
            chosen_items = [i for i, name in zip(inventory, names) if name in selected]

        if st.button("Generate Recipes with AI 🍳", type="primary"):
            if not chosen_items:
                st.warning("No items selected!")
            else:
                pantry_list = [f"{i['name']} - {i['amount']} {i['unit']}" for i in chosen_items]
                prompt = f"""
                You are an AI chef. Using ONLY these pantry items:\n{pantry_list}\n
                Suggest 3 unique recipes. Each recipe must include:
                - Title
                - Step-by-step instructions
                - Nutritional info per serving
                - Missing ingredients list (if any)
                Format clearly.
                """
                recipes = _ai_complete(prompt)
                st.markdown("### 🍽 AI Recipes")
                st.write(recipes)

                # Extract missing items for quick add
                if "Missing ingredients" in recipes:
                    st.markdown("#### ➕ Add Missing Ingredients to Inventory")
                    missing_input = st.text_area("Paste missing ingredients here (one per line):")
                    if st.button("Add to Inventory"):
                        for line in missing_input.split("\n"):
                            if line.strip():
                                _add_item(user_id, line.strip(), 1, "pcs", 0.0, 0)
                        st.success("Added missing items to inventory!")

    # ==================================
    # TAB 2 — Waste & Cost Insights
    # ==================================
    with tabs[1]:
        st.subheader("AI Analysis of Your Inventory")

        if st.button("Analyze My Pantry & Usage 💡"):
            inv_text = "\n".join(
                [f"{i['name']} - {i['amount']} {i['unit']} - expires {i['expiration']} - price/unit {i['price']}"
                 for i in inventory]
            )
            prompt = f"""
            You are an AI inventory and cost optimization expert.
            Analyze this inventory list:\n{inv_text}\n
            Provide:
            1. Items at high risk of expiry soon and ideas to use them up.
            2. Suggestions to save money (buy in bulk, substitute, skip).
            3. Ideas for reducing waste in the next month.
            """
            insights = _ai_complete(prompt)
            st.markdown("### 📊 AI Insights")
            st.write(insights)
