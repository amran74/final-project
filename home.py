import re
import streamlit as st
from db import (
    create_user, authenticate_user,
    get_user_by_phone, update_password_by_phone
)

# ---------- Helpers ----------
def _normalize_phone(p: str) -> str:
    return re.sub(r"[^\d+]", "", (p or "").strip())

def _password_strength(pw: str) -> tuple[int, str]:
    score = 0
    if len(pw) >= 8: score += 1
    if re.search(r"[A-Z]", pw): score += 1
    if re.search(r"[a-z]", pw): score += 1
    if re.search(r"\d", pw): score += 1
    if re.search(r"[^\w\s]", pw): score += 1
    score = min(4, score)
    labels = ["Very weak", "Weak", "Medium", "Strong", "Very strong"]
    colors = ["#ff4b4b", "#ff8c42", "#ffbf00", "#4caf50", "#2ecc71"]
    return score, f"<span style='color:{colors[score]}'>{labels[score]}</span>"

def _post_login(user_tuple):
    st.session_state["user_id"] = user_tuple[0]
    st.session_state["phone"] = user_tuple[1]
    st.session_state["name"] = user_tuple[2]
    st.session_state["authenticated"] = True
    st.rerun()

# ---------- Main ----------
def home():
    st.title("🏠 Smart Inventory Manager")

    tab_login, tab_register, tab_recover = st.tabs([
        "🔐 Login", "📝 Register", "🔑 Recover Password"
    ])

    # ===== LOGIN =====
    with tab_login:
        with st.form("login_form"):
            phone = st.text_input("📱 Phone Number")
            pw = st.text_input("🔑 Password", type="password")
            if st.form_submit_button("Login"):
                p = _normalize_phone(phone)
                user = authenticate_user(p, pw)
                if user:
                    _post_login(user)
                else:
                    st.error("❌ Invalid phone or password.")

    # ===== REGISTER =====
    with tab_register:
        with st.form("register_form"):
            name = st.text_input("👤 Full Name")
            phone = st.text_input("📱 Phone Number")
            pw = st.text_input("🔑 Password", type="password")
            score, label_html = _password_strength(pw)
            st.markdown(f"Strength: {label_html}", unsafe_allow_html=True)
            q = st.text_input("❓ Secret Question (for password recovery)")
            a = st.text_input("💬 Secret Answer")
            if st.form_submit_button("Create Account"):
                if not name or not phone or not pw or not q or not a:
                    st.warning("⚠️ All fields required.")
                elif score < 2:
                    st.warning("⚠️ Password too weak.")
                else:
                    if create_user(_normalize_phone(phone), pw, name, q.strip(), a.strip().lower()):
                        st.success("✅ Account created. You can now log in.")
                    else:
                        st.error("❌ Phone already registered.")

    # ===== RECOVER =====
    with tab_recover:
        stage = st.session_state.get("recover_stage", "enter_phone")

        if stage == "enter_phone":
            with st.form("recover_phone"):
                phone = st.text_input("📱 Enter your phone number")
                if st.form_submit_button("Next"):
                    p = _normalize_phone(phone)
                    user = get_user_by_phone(p)
                    if not user:
                        st.error("❌ Phone not found.")
                    else:
                        st.session_state["recover_phone"] = p
                        st.session_state["recover_question"] = user[3]  # secret_question column
                        st.session_state["recover_answer"] = user[4]    # secret_answer column
                        st.session_state["recover_stage"] = "answer"
                        st.rerun()

        elif stage == "answer":
            st.info(f"❓ Secret Question: {st.session_state['recover_question']}")
            with st.form("recover_answer"):
                ans = st.text_input("💬 Your Answer")
                if st.form_submit_button("Verify"):
                    if ans.strip().lower() == st.session_state["recover_answer"]:
                        st.session_state["recover_stage"] = "reset_pw"
                        st.rerun()
                    else:
                        st.error("❌ Incorrect answer.")

        elif stage == "reset_pw":
            with st.form("reset_pw_form"):
                new_pw = st.text_input("🔑 New Password", type="password")
                score, label_html = _password_strength(new_pw)
                st.markdown(f"Strength: {label_html}", unsafe_allow_html=True)
                if st.form_submit_button("Reset Password"):
                    if score < 2:
                        st.warning("⚠️ Password too weak.")
                    else:
                        update_password_by_phone(st.session_state["recover_phone"], new_pw)
                        st.success("✅ Password updated. You can now log in.")
                        for k in ["recover_stage", "recover_phone", "recover_question", "recover_answer"]:
                            st.session_state.pop(k, None)
6+
