import streamlit as st
from db import create_user, authenticate_user

def auth_page():
    st.set_page_config(page_title="Login | Smart Inventory", page_icon="🔐")

    # Title
    st.title("🔐 Welcome to Smart Food Inventory")

    # Tabs
    tab1, tab2 = st.tabs(["Login 🔑", "Register 📝"])

    with tab1:
        st.subheader("Login to your account")

        phone_login = st.text_input("Phone Number", max_chars=20)
        password_login = st.text_input("Password", type="password")

        if st.button("Login"):
            user = authenticate_user(phone_login, password_login)
            if user:
                st.session_state["user_id"] = user[0]
                st.session_state["phone"] = user[1]
                st.session_state["authenticated"] = True
                st.success(f"Logged in successfully as {user[1]}")
            else:
                st.error("Invalid phone number or password.")

    with tab2:
        st.subheader("Register a new account")

        phone_register = st.text_input("New Phone Number", max_chars=20)
        password_register = st.text_input("New Password", type="password")

        if st.button("Register"):
            success = create_user(phone_register, password_register)
            if success:
                st.success("Account created! You can now login.")
            else:
                st.error("Phone already registered. Try another.")
