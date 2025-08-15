# AI_Assistant.py — Premium AI integration for Smart Inventory
import streamlit as st
import openai
import db
from datetime import date

st.set_page_config(page_title="🤖 AI Assistant", page_icon="🤖", layout="wide")

# ==============================
# Setup OpenAI
# ==============================
openai.api_key = st.secrets.get("OPENAI_API_KEY", "")

MODEL = "gpt-4.1"

# ==============================
# Helper: Get inventory summary
# ==============================
def get_inventory_summary(user_id):
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("SELECT name, amount, unit, expiration, price_per_unit FROM inventory WHERE user_id=?", (user_id,))
    items = c.fetchall()
    conn.close()
    return items

# ==============================
# Helper: Pretty inventory text
# ==============================
def format_inventory_for_ai(items):
    lines = []
    today = date.today()
    for name, amount, unit, exp, price in items:
        exp_days = ""
        try:
            exp_days = (date.fromisoformat(exp) - today).days
            exp_days = f"{exp_days} days left" if exp_days >= 0 else f"Expired {-exp_days} days ago"
        except:
            exp_days = "Unknown expiry"
        lines.append(f"{name} — {amount} {unit}, expires in {exp_days}, ₪{price:.2f} per {unit}")
    return "\n".join(lines) if lines else "No items in inventory."

# ==============================
# Core AI query function
# ==============================
def ask_ai(prompt):
    try:
        response = openai.ChatCompletion.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful kitchen and inventory assistant with expert cooking and budgeting skills."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=800
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        return f"⚠ Error: {str(e)}"

# ==============================
# Page UI
# ==============================
st.title("🤖 Smart AI Assistant")
st.caption("Powered by GPT-4.1 — Connected to your live inventory")

if "user_id" not in st.session_state:
    st.warning("⚠ Please log in to use the AI Assistant.")
    st.stop()

user_id = st.session_state["user_id"]

mode = st.radio(
    "Choose AI Mode:",
    [
        "🍳 Smart Recipe Maker",
        "📅 Meal Planner",
        "💬 Pantry Chat",
        "💰 Cost Optimization"
    ],
    horizontal=True
)

inventory_items = get_inventory_summary(user_id)
inventory_text = format_inventory_for_ai(inventory_items)

# ==============================
# Smart Recipe Maker
# ==============================
if mode == "🍳 Smart Recipe Maker":
    st.subheader("Create Recipes from Your Inventory")
    meal_type = st.selectbox("Meal Type", ["Any", "Breakfast", "Lunch", "Dinner", "Snack"])
    servings = st.number_input("Servings", min_value=1, value=2)

    if st.button("Generate Recipe"):
        prompt = f"""
        I have the following inventory:\n{inventory_text}\n
        Please suggest a {meal_type} recipe for {servings} servings using mainly items I already have.
        If items are missing, list them clearly as 'MISSING INGREDIENTS:' at the end.
        """
        recipe = ask_ai(prompt)
        st.markdown("### 🍽 Suggested Recipe")
        st.write(recipe)

# ==============================
# Meal Planner
# ==============================
elif mode == "📅 Meal Planner":
    st.subheader("Plan Your Meals")
    days = st.slider("Number of days", 1, 7, 3)
    if st.button("Generate Meal Plan"):
        prompt = f"""
        My inventory:\n{inventory_text}\n
        Plan healthy, budget-friendly meals for {days} days, prioritizing items close to expiry.
        Include breakfast, lunch, and dinner for each day.
        """
        plan = ask_ai(prompt)
        st.markdown("### 📅 Meal Plan")
        st.write(plan)

# ==============================
# Pantry Chat
# ==============================
elif mode == "💬 Pantry Chat":
    st.subheader("Chat with Your Pantry")
    user_q = st.text_area("Ask me anything about your pantry or cooking:")
    if st.button("Ask"):
        prompt = f"My inventory:\n{inventory_text}\nUser question: {user_q}"
        answer = ask_ai(prompt)
        st.markdown("### 💡 Answer")
        st.write(answer)

# ==============================
# Cost Optimization
# ==============================
elif mode == "💰 Cost Optimization":
    st.subheader("Analyze & Optimize Costs")
    if st.button("Analyze"):
        prompt = f"""
        My inventory:\n{inventory_text}\n
        Analyze the cost-effectiveness of my inventory.
        Suggest cheaper substitutes without sacrificing too much quality, and give cost per meal ideas.
        """
        advice = ask_ai(prompt)
        st.markdown("### 💰 Optimization Suggestions")
        st.write(advice)
