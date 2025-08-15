# CalendarView.py — Premium, balanced homepage
import streamlit as st
from datetime import date, datetime
from streamlit_calendar import calendar
import db
import openai

# ==============================
# Styles
# ==============================
st.markdown("""
<style>
.section {
    margin-bottom: 2rem;
}
.kpi-card {
    background:#0f1428;
    border:1px solid #1e2a44;
    border-radius:12px;
    padding:14px;
    text-align:center;
    box-shadow:0 0 8px rgba(0,0,0,0.15);
}
.kpi-card .val {
    font-weight:700;
    font-size:22px;
    color:#e8f2ff;
}
.kpi-card .lbl {
    font-size:13px;
    color:#9bb3c7;
}
.upcoming-table {
    background:#121629;
    border-radius:10px;
    border:1px solid #1e2a44;
    padding:10px;
}
.upcoming-item {
    padding:6px 0;
    border-bottom:1px solid rgba(255,255,255,0.05);
    font-size:14px;
    color:#dfe9f3;
}
.upcoming-item:last-child {
    border-bottom:none;
}
.smart-suggestions {
    background:#0f1428;
    border:1px solid #1e2a44;
    border-radius:10px;
    padding:14px;
}
.smart-suggestions h4 {
    color:#9bd7ff;
}
</style>
""", unsafe_allow_html=True)


# ==============================
# AI Helper
# ==============================
def get_ai_tip(user_id: int) -> str:
    """Generate AI suggestion based on expiring items."""
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT name, amount, unit, expiration
        FROM inventory
        WHERE user_id=? AND expiration >= ? 
        ORDER BY expiration ASC
        LIMIT 5
    """, (user_id, date.today().isoformat()))
    items = c.fetchall()
    conn.close()

    if not items:
        return "No items are expiring soon. Keep up the great work! ✅"

    items_str = "\n".join([f"- {n} ({a} {u}) expiring on {e}" for n, a, u, e in items])

    prompt = f"""
    You are a smart kitchen assistant. Based on the following items expiring soon:
    {items_str}

    Give me 1 short tip of the day to help reduce waste, and 2 quick meal/snack ideas
    using one or more of these items. Be concise and friendly.
    """
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": "You are a concise kitchen coach."},
                      {"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0.7
        )
        return resp.choices[0].message["content"].strip()
    except Exception:
        return "Tip of the day: Store perishables in the fridge and label them with the date."


# ==============================
# Homepage View
# ==============================
def calendar_view():
    st.title(f"👋 Welcome, {st.session_state.get('name', 'User')}")

    uid = st.session_state.get("user_id")
    if not uid:
        st.warning("Please log in to see your dashboard.")
        return

    # Section 1: AI Overview
    with st.container():
        st.subheader("💡 Today's Smart Insight")
        st.write(get_ai_tip(uid))

    # Section 2: KPI Cards
    items, used, expired, lost = db.get_monthly_summary(uid)["month"], None, None, None
    total_items, used_steps, expired_steps, money_lost = (
        db._kpis(uid) if hasattr(db, "_kpis") else (
            db.get_connection().execute("SELECT COUNT(*) FROM inventory WHERE user_id=?", (uid,)).fetchone()[0],
            db.get_monthly_summary(uid)["used_steps"],
            db.get_monthly_summary(uid)["expired_steps"],
            db.get_monthly_summary(uid)["money_lost"],
        )
    )
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.markdown(f"<div class='kpi-card'><div class='val'>{total_items}</div><div class='lbl'>Items in stock</div></div>", unsafe_allow_html=True)
    with k2:
        st.markdown(f"<div class='kpi-card'><div class='val'>{used_steps}</div><div class='lbl'>Used steps (month)</div></div>", unsafe_allow_html=True)
    with k3:
        st.markdown(f"<div class='kpi-card'><div class='val'>{expired_steps}</div><div class='lbl'>Expired steps (month)</div></div>", unsafe_allow_html=True)
    with k4:
        st.markdown(f"<div class='kpi-card'><div class='val'>₪{money_lost:.2f}</div><div class='lbl'>Money lost (month)</div></div>", unsafe_allow_html=True)

    # Section 3: Upcoming Expirations
    st.markdown("### ⏳ Upcoming Expirations")
    conn = db.get_connection()
    c = conn.cursor()
    c.execute("""
        SELECT name, amount, unit, expiration
        FROM inventory
        WHERE user_id=? AND expiration >= ?
        ORDER BY expiration ASC
        LIMIT 5
    """, (uid, date.today().isoformat()))
    upcoming = c.fetchall()
    conn.close()

    if upcoming:
        with st.container():
            st.markdown("<div class='upcoming-table'>", unsafe_allow_html=True)
            for n, a, u, e in upcoming:
                st.markdown(f"<div class='upcoming-item'>📌 {n} — {a} {u} (exp {e})</div>", unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("No upcoming expirations.")

    # Section 4: Calendar
    st.markdown("### 📅 Calendar")
    events = [{"title": f"{n} expires", "start": e} for n, _, _, e in upcoming]
    calendar(events, options={"initialView": "dayGridMonth"})

