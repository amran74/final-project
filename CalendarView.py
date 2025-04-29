import streamlit as st
from streamlit_calendar import calendar
import sqlite3
from datetime import datetime, date

def get_connection():
    return sqlite3.connect("inventory.db")

def get_user_items(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT name, expiration, type FROM inventory WHERE user_id = ?", (user_id,))
    items = cursor.fetchall()
    conn.close()
    return items

def calendar_view():
    st.title("📅 Expiration Calendar")

    if "user_id" not in st.session_state:
        st.warning("⚠️ Please login first.")
        return

    user_id = st.session_state["user_id"]
    items = get_user_items(user_id)

    events = []
    for name, expiration, food_type in items:
        exp_date = datetime.strptime(expiration, "%Y-%m-%d").date()
        today = date.today()
        days_left = (exp_date - today).days

        if days_left < 0:
            color = "red"
        elif days_left <= 2:
            color = "orange"
        else:
            color = "green"

        events.append({
            "title": f"{name} ({food_type})",
            "start": expiration,
            "end": expiration,
            "color": color
        })

    options = {
        "initialView": "dayGridMonth",
        "headerToolbar": {
            "left": "prev,next today",
            "center": "title",
            "right": "dayGridMonth,timeGridWeek"
        }
    }

    calendar(events=events, options=options)
