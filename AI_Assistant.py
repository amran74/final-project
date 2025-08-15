import streamlit as st
import openai
import db
from datetime import date

# Make sure you set your OpenAI API key in environment or Streamlit secrets
# Example: st.secrets["OPENAI_API_KEY"]
openai.api_key = st.secrets.get("OPENAI_API_KEY", "")

def ai_assistant():
    st.title("🤖 Smart AI Assistant")

    # --- User greeting ---
    user_name = st.session_state.get("name", "User")
    st.write(f"Hello **{user_name}**, how can I help you with your inventory today?")

    # --- Assistant mode selector ---
    mode = st.selectbox(
        "Choose an AI mode:",
        [
            "💬 General Chat",
            "📦 Recipe Suggestions (Based on My Inventory)",
            "🛒 Suggest Items to Restock",
            "🍽️ Create Meal Plan from Pantry",
        ]
    )

    # --- General chat mode ---
    if mode == "💬 General Chat":
        prompt = st.text_area("Ask the AI anything...")
        if st.button("Send"):
            if not prompt.strip():
                st.warning("Please enter a message.")
            else:
                with st.spinner("Thinking..."):
                    try:
                        response = openai.ChatCompletion.create(
                            model="gpt-4o-mini",
                            messages=[
                                {"role": "system", "content": "You are a helpful assistant for a smart inventory management app."},
                                {"role": "user", "content": prompt}
                            ]
                        )
                        st.markdown("**AI:** " + response.choices[0].message.content)
                    except Exception as e:
                        st.error(f"Error: {e}")

    # --- Recipe suggestions ---
    elif mode == "📦 Recipe Suggestions (Based on My Inventory)":
        user_id = st.session_state.get("user_id")
        if not user_id:
            st.warning("Please log in to use this feature.")
            return

        items = _get_inventory_list(user_id)
        if not items:
            st.warning("Your inventory is empty.")
            return

        st.write("**Your Pantry:** " + ", ".join(items))
        if st.button("Suggest Recipes"):
            with st.spinner("AI is finding recipes..."):
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "You are a professional chef AI that suggests recipes only using the provided ingredients."},
                            {"role": "user", "content": f"My pantry contains: {', '.join(items)}. Suggest 5 creative recipes I can make."}
                        ]
                    )
                    st.markdown(response.choices[0].message.content)
                except Exception as e:
                    st.error(f"Error: {e}")

    # --- Restock suggestions ---
    elif mode == "🛒 Suggest Items to Restock":
        user_id = st.session_state.get("user_id")
        if not user_id:
            st.warning("Please log in to use this feature.")
            return

        low_stock_items = _get_low_stock(user_id)
        if not low_stock_items:
            st.info("✅ All items are well-stocked.")
            return

        st.write("**Low Stock Items:** " + ", ".join(low_stock_items))
        with st.spinner("AI is analyzing restock priorities..."):
            try:
                response = openai.ChatCompletion.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are an inventory optimization expert AI."},
                        {"role": "user", "content": f"These items are low in stock: {', '.join(low_stock_items)}. Suggest a prioritized restocking plan."}
                    ]
                )
                st.markdown(response.choices[0].message.content)
            except Exception as e:
                st.error(f"Error: {e}")

    # --- Meal plan ---
    elif mode == "🍽️ Create Meal Plan from Pantry":
        user_id = st.session_state.get("user_id")
        if not user_id:
            st.warning("Please log in to use this feature.")
            return

        items = _get_inventory_list(user_id)
        if not items:
            st.warning("Your inventory is empty.")
            return

        days = st.slider("Meal plan for how many days?", 1, 14, 7)
        if st.button("Generate Meal Plan"):
            with st.spinner("AI is generating your meal plan..."):
                try:
                    response = openai.ChatCompletion.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "You are a meal planning assistant AI."},
                            {"role": "user", "content": f"My pantry contains: {', '.join(items)}. Create a {days}-day meal plan using only these ingredients where possible."}
                        ]
                    )
                    st.markdown(response.choices[0].message.content)
                except Exception as e:
                    st.error(f"Error: {e}")

# ==============================
# Helper functions
# ==============================

def _get_inventory_list(user_id):
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("SELECT name FROM inventory WHERE user_id=? AND amount > 0", (user_id,))
    items = [row[0] for row in c.fetchall()]
    conn.close()
    return items

def _get_low_stock(user_id):
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("SELECT name FROM inventory WHERE user_id=? AND amount <= 2", (user_id,))
    items = [row[0] for row in c.fetchall()]
    conn.close()
    return items
