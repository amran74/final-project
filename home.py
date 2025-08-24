# home.py — polished auth screen for Streamlit
import streamlit as st
from typing import Tuple
import db

# ---------------------------
# Password strength helper
# ---------------------------
def _password_strength(pw: str) -> Tuple[int, str]:
    score = 0
    if len(pw) >= 8: score += 1
    if any(c.islower() for c in pw) and any(c.isupper() for c in pw): score += 1
    if any(c.isdigit() for c in pw): score += 1
    if any(c in "!@#$%^&*()-_=+[]{};:'\",.<>?/\\|" for c in pw): score += 1
    labels = ["❌ Very weak", "⚠ Weak", "🟡 Medium", "🟢 Strong", "✅ Very strong"]
    return score, labels[score]

# ---------------------------
# CSS
# ---------------------------
def _inject_css():
    st.markdown("""
    <style>
      /* Page background */
      body, .stApp {
        background: radial-gradient(1200px 600px at 10% 10%, #0f1a39, #0a1026) fixed;
      }
      /* Center frame */
      .auth-wrap {
        max-width: 880px;
        margin: 5vh auto 6rem auto;
        padding: 0 1rem;
      }
      /* Glass card */
      .auth-card {
        background: rgba(18, 22, 41, 0.75);
        border: 1px solid rgba(65, 108, 181, 0.25);
        box-shadow: 0 12px 35px rgba(0,0,0,0.35);
        backdrop-filter: blur(8px);
        border-radius: 22px;
        padding: 28px 28px 22px 28px;
      }
      /* Title area */
      .brand {
        display: flex; align-items: center; gap: 14px; margin-bottom: 8px;
      }
      .brand h1 {
        font-size: 28px; margin: 0; color: #e9f2ff; letter-spacing: .2px;
      }
      .brand-sub {
        color:#9ab6d6; font-size: 13px; margin: 2px 0 16px 46px;
      }
      /* Tabs styling */
      .stTabs [data-baseweb="tab-list"] { gap: 6px; }
      .stTabs [data-baseweb="tab"] {
        background: #10162e; color: #cfe3ff; border-radius: 12px 12px 0 0;
        padding: 8px 14px; border: 1px solid #1e2a44;
      }
      .stTabs [aria-selected="true"] {
        background: #0e2442; border-color:#3aa0ff; color:#e9f6ff;
      }
      /* Inputs */
      .stTextInput>div>div>input, .stTextArea textarea {
        border-radius: 12px; border: 1px solid #27334f; background:#0f152c; color:#e9f2ff;
      }
      /* Buttons */
      .stButton>button {
        width: 100%; border-radius: 12px; height: 44px;
        border: 1px solid #1f3b6a; background: linear-gradient(180deg,#2f6feb,#2159c6);
        color: #fff; font-weight: 600;
      }
      .stButton>button:hover { filter: brightness(1.03); border-color:#3aa0ff; }
      /* Helper rows */
      .row { display:flex; gap:12px; }
      .col { flex:1; }
      /* Strength bar */
      .meter { height: 8px; border-radius: 999px; background:#172036; border:1px solid #24314b; }
      .meter > div { height: 100%; border-radius: 999px; }
    </style>
    """, unsafe_allow_html=True)

# ---------------------------
# View
# ---------------------------
def home():
    _inject_css()

    st.markdown('<div class="auth-wrap"><div class="auth-card">', unsafe_allow_html=True)

    # Brand
    col_logo, col_title = st.columns([1, 6], vertical_alignment="center")
    with col_logo:
        st.image("https://img.icons8.com/fluency/96/lock.png", width=42)
    with col_title:
        st.markdown('<div class="brand"><h1>Smart Inventory Manager</h1></div>', unsafe_allow_html=True)
        st.markdown('<div class="brand-sub">Sign in to continue, or create an account in seconds.</div>', unsafe_allow_html=True)

    # Tabs
    tab_login, tab_register, tab_recover = st.tabs(["🔑 Login", "🆕 Register", "♻ Recover"])

    # -------- Login --------
    with tab_login:
        st.write("")
        phone = st.text_input("📱 Phone number", max_chars=20, key="login_phone")
        pw = st.text_input("🔒 Password", type="password", key="login_pw")
        c1, c2 = st.columns([1,1])
        with c1:
            remember = st.checkbox("Remember me", value=True)
        with c2:
            st.caption("")

        if st.button("Login"):
            user = db.authenticate_user(phone, pw)
            if user:
                st.session_state["authenticated"] = True
                st.session_state["user_id"] = user[0]
                st.session_state["phone"] = user[1]
                st.session_state["name"] = user[2]
                # soft flag so App.py can jump to Home once
                st.session_state["just_logged_in"] = True
                st.success("Welcome back.")
                st.rerun()
            else:
                st.error("Invalid phone or password.")

    # -------- Register --------
    with tab_register:
        st.write("")
        r1, r2 = st.columns([1,1])
        with r1:
            phone_r = st.text_input("📱 Phone number", max_chars=20, key="reg_phone")
            name_r  = st.text_input("👤 Name", key="reg_name")
            pw_r    = st.text_input("🔒 Password", type="password", key="reg_pw")
        with r2:
            secret_q = st.text_input("❓ Secret question (for recovery)", key="reg_q")
            secret_a = st.text_input("📝 Secret answer", key="reg_a")
            # live strength meter
            if pw_r:
                score, label = _password_strength(pw_r)
                # color per score
                color = ["#e05252","#f2a93b","#e5d04a","#35c06d","#12d48b"][score]
                st.markdown(
                    f"""<div class="meter"><div style="width:{(score/4)*100}%; background:{color}"></div></div>""",
                    unsafe_allow_html=True
                )
                st.caption(label)

        agree = st.checkbox("I agree to the Terms of Use and Privacy Policy", value=True)
        st.write("")
        if st.button("Register", disabled=not agree):
            if not phone_r or not pw_r or not name_r:
                st.error("Please fill in all required fields.")
            else:
                ok = db.create_user(phone_r, pw_r, name_r, secret_q, secret_a)
                if ok:
                    st.success("Account created. You can now log in.")
                else:
                    st.error("Phone number already exists.")

    # -------- Recover --------
    with tab_recover:
        st.write("")
        phone_f = st.text_input("📱 Phone number", key="rec_phone")
        if st.button("Find account"):
            if not phone_f:
                st.error("Enter your phone number.")
            else:
                user = db.get_user_by_phone(phone_f)
                if user:
                    st.info(f"Secret question: {user[3] or '—'}")
                    ans = st.text_input("📝 Your answer", key="rec_ans")
                    new_pw = st.text_input("🔑 New password", type="password", key="rec_new")
                    if st.button("Reset password"):
                        if (ans or "").lower() == (user[4] or "").lower():
                            db.update_password_by_phone(phone_f, new_pw)
                            st.success("Password updated. You can log in now.")
                        else:
                            st.error("Incorrect answer.")
                else:
                    st.error("No account with that phone.")

    st.markdown("</div></div>", unsafe_allow_html=True)
