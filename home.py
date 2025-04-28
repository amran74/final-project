
import streamlit as st
import sqlite3
from db import create_user, authenticate_user

st.set_page_config(page_title="Login | Smart Inventory", page_icon="📱")

st.title("📱 Welcome to Smart Food Inventory")

# --- Login / Register Tabs ---
tab1, tab2 = st.tabs(["🔑 Login", "📝 Register"])

# --- Login ---
with tab1:
    st.subheader("Login")
    phone_login = st.text_input("Phone Number", max_chars=20)
    password_login = st.text_input("Password", type="password")

    if st.button("Login"):
        user = authenticate_user(phone_login, password_login)
        if user:
            st.session_state["user_id"] = user[0]
            st.session_state["phone"] = user[1]
            st.success(f"✅ Logged in as {user[1]}")
        else:
            st.error("❌ Invalid phone number or password.")

# --- Register ---
with tab2:
    st.subheader("Create New Account")
    phone_register = st.text_input("Phone Number (for new account)", max_chars=20, key="register_phone")
    password_register = st.text_input("Password (for new account)", type="password", key="register_password")

    if st.button("Register"):
        if phone_register and password_register:
            success = create_user(phone_register, password_register)
            if success:
                st.success("✅ Account created! You can now login.")
            else:
                st.error("❌ Phone number already exists.")
        else:
            st.warning("⚠️ Please enter both phone number and password.")
