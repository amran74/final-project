# CalendarView.py — Premium Home Dashboard
import streamlit as st
from datetime import date, datetime, timedelta
from streamlit_calendar import calendar
import db
import openai

# ========= CONFIG =========
CALENDAR_HEIGHT = 450  # Smaller for balance
MAX_UPCOMING_ITEMS = 5

# ========= AI HELPER =========
def get_ai_dashboard_tips(user_name: str, items_due: list) -> dict:
    """
    Generate AI-powered tips using OpenAI.
    """
    item_list = ", ".join([f"{n} ({d})" for n, d in items_due]) if items_due else "no urgent items"
    prompt = f"""
    You are a smart kitchen assistant for {user_name}.
    Based on these urgent items: {item_list}, give:
    1 short waste reduction tip,
    1 short storage optimization tip,
    and 1 short meal idea using at least one urgent item.
    Keep each under 20 words.
    """
    try:
        res = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=120
        )
        text = res.choices[0].message["content"].strip()
        parts = text.split("\n")
        return {
            "waste_tip": parts[0] if len(parts) > 0 else "",
            "storage_tip": parts[1] if len(parts) > 1 else "",
            "meal_idea": parts[2] if len(parts) > 2 else ""
        }
    except Exception as e:
        return {
            "waste_tip": "Keep track of expiry dates weekly.",
            "storage_tip": "Store produce in breathable bags.",
            "meal_idea": "Make a stir fry with veggies."
        }

# ========= MAIN VIEW =========
def calendar_view():
    if "user_id" not in st.session_state:
        st.warning("Please log in first.")
        return

    user_id = st.session_state["user_id"]
    user_name = st.session_state.get("name", "User")

    # ---- Get inventory ----
    conn = db.get_connection()
    c = conn.cursor()
    today = date.today()
    c.execute("""
        SELECT name, expiration, id
        FROM inventory
        WHERE user_id = ?
        ORDER BY date(expiration) ASC
    """, (user_id,))
    all_items = c.fetchall()
    conn.close()

    upcoming_items = [
        (name, exp, iid)
        for name, exp, iid in all_items
        if exp and date.fromisoformat(exp) <= today + timedelta(days=7)
    ][:MAX_UPCOMING_ITEMS]

    # ---- AI tips ----
    ai_tips = get_ai_dashboard_tips(user_name, [(n, d) for n, d, _ in upcoming_items])

    # ---- Stats ----
    stats = db.get_monthly_summary(user_id)

    # ========= LAYOUT =========
    st.markdown(f"## 👋 Welcome back, {user_name}")
    st.markdown("### 🧠 Your Smart Coach Today")

    col1, col2, col3 = st.columns(3)
    col1.info(f"💡 Waste Tip:\n{ai_tips['waste_tip']}")
    col2.success(f"📦 Storage Tip:\n{ai_tips['storage_tip']}")
    col3.warning(f"🍽 Meal Idea:\n{ai_tips['meal_idea']}")

    # ---- Stats cards ----
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("📦 Total Items", len(all_items))
    k2.metric("✅ Used (mo)", stats["used_steps"])
    k3.metric("⛔ Expired (mo)", stats["expired_steps"])
    k4.metric("💰 Money Lost (mo)", f"₪{stats['money_lost']:.2f}")

    # ---- Upcoming expirations ----
    st.markdown("### ⏳ Items Expiring Soon")
    if upcoming_items:
        for name, exp, iid in upcoming_items:
            cols = st.columns([3, 2, 1, 1])
            cols[0].write(f"**{name}**")
            cols[1].write(f"📅 {exp}")
            if cols[2].button("✅ Use", key=f"use_{iid}"):
                db.use_one_step(iid)
                st.rerun()
            if cols[3].button("❌ Expire", key=f"exp_{iid}"):
                db.expire_all(iid)
                st.rerun()
    else:
        st.info("No items expiring soon 🎉")

    # ---- Compact Calendar ----
    st.markdown("### 📅 Your Week at a Glance")
    events = []
    for name, exp, iid in all_items:
        events.append({
            "title": name,
            "start": exp,
            "end": exp,
            "color": "#ff6b6b" if date.fromisoformat(exp) < today else "#1dd1a1"
        })

    calendar(
        events=events,
        options={
            "initialView": "listWeek",
            "height": CALENDAR_HEIGHT
        }
    )

