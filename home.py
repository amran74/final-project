import streamlit as st
from db import create_user, authenticate_user

def home():
    st.set_page_config(page_title="Login | Smart Inventory", page_icon="🔐")
    st.title("🏠 Welcome to Smart Inventory Manager")

    tab1, tab2 = st.tabs(["Login 🔐", "Register 📝"])

    # ------------------- Login -------------------
    with tab1:
        st.subheader("Login to your account")

        phone_login = st.text_input("Phone Number", max_chars=20)
        password_login = st.text_input("Password", type="password")

        if st.button("Login"):
            user = authenticate_user(phone_login, password_login)
            if user:
                st.session_state["user_id"] = user[0]
                st.session_state["phone"] = user[1]
                st.session_state["name"] = user[2]
                st.session_state["authenticated"] = True
                st.success(f"✅ Welcome back, {user[2]}")

                # ✅ Use rerun instead of switch_page (for dynamic routing)
                st.experimental_rerun()
            else:
                st.error("❌ Invalid phone number or password.")

    # ------------------ Register ------------------
    with tab2:
        st.subheader("Register a new account")

        name_register = st.text_input("Full Name", max_chars=50)
        phone_register = st.text_input("New Phone Number", max_chars=20)
        password_register = st.text_input("New Password", type="password")

        if st.button("Register"):
            if not name_register.strip() or not phone_register.strip() or not password_register.strip():
                st.warning("⚠️ All fields are required.")
            else:
                success = create_user(phone_register, password_register, name_register)
                if success:
                    st.success("✅ Account created successfully. You can now log in.")
                else:
                    st.error("❌ Phone number already registered.")
