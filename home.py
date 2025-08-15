import streamlit as st
from typing import Tuple
import db

# ==============================
# Password strength check
# ==============================

def _password_strength(pw: str) -> Tuple[int, str]:
    score = 0
    if len(pw) >= 8:
        score += 1
    if any(c.islower() for c in pw) and any(c.isupper() for c in pw):
        score += 1
    if any(c.isdigit() for c in pw):
        score += 1
    if any(c in "!@#$%^&*()-_=+[]{};:'\",.<>?/\\|" for c in pw):
        score += 1

    levels = {
        0: ("❌ Very Weak", "red"),
        1: ("⚠ Weak", "orange"),
        2: ("🟡 Medium", "gold"),
        3: ("🟢 Strong", "green"),
        4: ("✅ Very Strong", "lime")
    }
    return score, levels[score][0]

# ==============================
# Home Page
# ==============================

def home():
    st.title("🏠 Welcome to Smart Inventory Manager")

    tab_login, tab_register, tab_recover = st.tabs(["🔑 Login", "🆕 Register", "♻ Recover Password"])

    # --- Login ---
    with tab_login:
        st.subheader("Login to Your Account")
        phone = st.text_input("📱 Phone Number", max_chars=20)
        password = st.text_input("🔒 Password", type="password")

        if st.button("Login"):
            user = db.authenticate_user(phone, password)
            if user:
                st.session_state["user_id"] = user[0]
                st.session_state["phone"] = user[1]
                st.session_state["name"] = user[2]
                st.success(f"✅ Welcome back, {user[2]}!")
                st.experimental_rerun()
            else:
                st.error("❌ Invalid phone number or password.")

    # --- Register ---
    with tab_register:
        st.subheader("Create a New Account")
        phone_r = st.text_input("📱 Phone Number", max_chars=20, key="reg_phone")
        name_r = st.text_input("👤 Name", key="reg_name")
        password_r = st.text_input("🔒 Password", type="password", key="reg_pw")
        secret_q = st.text_input("❓ Secret Question (for password recovery)", key="reg_q")
        secret_a = st.text_input("📝 Secret Answer", key="reg_a")

        if password_r:
            score, label = _password_strength(password_r)
            st.write(f"Password Strength: {label}")

        if st.button("Register"):
            if not phone_r or not password_r or not name_r:
                st.error("⚠ Please fill in all required fields.")
            else:
                ok = db.create_user(phone_r, password_r, name_r, secret_q, secret_a)
                if ok:
                    st.success("✅ Account created! You can now log in.")
                else:
                    st.error("❌ Phone number already exists.")

    # --- Recover Password ---
    with tab_recover:
        st.subheader("Recover Your Account")
        phone_f = st.text_input("📱 Phone Number", key="rec_phone")

        if phone_f:
            user = db.get_user_by_phone(phone_f)
            if user:
                st.info(f"Secret Question: {user[3]}")
                answer = st.text_input("📝 Your Answer", key="rec_a")
                new_pw = st.text_input("🔑 New Password", type="password", key="rec_pw")

                if st.button("Reset Password"):
                    if answer.lower() == (user[4] or "").lower():
                        db.update_password_by_phone(phone_f, new_pw)
                        st.success("✅ Password updated! You can log in now.")
                    else:
                        st.error("❌ Incorrect answer.")
            else:
                st.error("❌ Phone not found.")
