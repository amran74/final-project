# home.py — modern, reliable auth UI (centered card, clean tabs, strength meter)
import streamlit as st
from typing import Tuple
import db

st.set_page_config(page_title="Smart Inventory | Sign in", page_icon="🔐", layout="centered")

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
      :root {
        --bg1: #0b1220;         /* page background gradient */
        --bg2: #0f172a;
        --panel: rgba(17, 24, 39, 0.78);
        --border: rgba(88, 111, 175, 0.28);
        --accent: #3b82f6;      /* primary */
        --text: #e6eeff;
        --muted: #9ab6d6;
        --input: #101731;
      }

      /* Calm background */
      .stApp {
        background: radial-gradient(1100px 600px at 15% 10%, var(--bg2), var(--bg1)) fixed !important;
      }

      /* Center the auth card vertically */
      .auth-wrap {
        min-height: calc(100vh - 6rem);
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 2rem 1rem;
      }

      /* Card */
      .auth-card {
        width: min(92vw, 520px);
        background: var(--panel);
        border: 1px solid var(--border);
        backdrop-filter: blur(8px);
        border-radius: 20px;
        padding: 22px 22px 18px;
        box-shadow: 0 18px 50px rgba(0,0,0,0.35);
      }
      .auth-card:after {
        content:"";
        position:absolute; inset:-2px; border-radius:22px; padding:1px;
        background: linear-gradient(180deg, var(--accent), rgba(255,255,255,0));
        -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
        -webkit-mask-composite: xor; mask-composite: exclude;
        opacity:.15; pointer-events:none;
      }

      /* Brand */
      .brand { display:flex; align-items:center; gap:10px; margin-bottom:4px; }
      .brand .emoji { font-size: 26px; }
      .brand h1 { font-size: 26px; color: var(--text); margin: 0; letter-spacing:.2px; }
      .brand-sub { color: var(--muted); font-size: 13px; margin: 2px 0 12px 36px; }

      /* Tabs */
      .stTabs [data-baseweb="tab-list"] { gap: 6px; }
      .stTabs [data-baseweb="tab"] {
        background: #0f152c; color:#cfe3ff; border-radius:12px 12px 0 0;
        padding: 8px 14px; border:1px solid #1e2a44;
      }
      .stTabs [aria-selected="true"] {
        background: #0e2442; border-color: var(--accent); color:#e9f6ff;
      }

      /* Inputs */
      .stTextInput>div>div, .stPassword>div>div, .stTextArea>div>div {
        border-radius: 12px;
        border:1px solid #27334f;
        background: var(--input);
      }
      .stTextInput input, .stTextArea textarea { color: var(--text); }
      .stTextInput>div>div:focus-within,
      .stPassword>div>div:focus-within,
      .stTextArea>div>div:focus-within {
        box-shadow: 0 0 0 2px var(--accent);
        border-color: var(--accent);
      }

      /* Buttons */
      .stButton>button {
        width: 100%; height: 44px; border-radius: 12px;
        border: 1px solid rgba(31,59,106,0.9);
        background: linear-gradient(180deg, #4b8bf7, #2f6feb);
        color: #fff; font-weight: 600;
        transition: transform .03s ease, filter .15s ease;
      }
      .stButton>button:active { transform: translateY(1px); }
      .stButton>button:hover { filter: brightness(1.05); }

      /* Strength meter */
      .meter { height: 8px; border-radius: 999px; background:#172036; border:1px solid #24314b; }
      .meter > div { height: 100%; border-radius: 999px; }
    </style>
    """, unsafe_allow_html=True)

def _strength_meter(score: int):
    color = ["#e05252","#f2a93b","#e5d04a","#35c06d","#12d48b"][score]
    st.markdown(
        f"""<div class="meter"><div style="width:{(score/4)*100}%; background:{color}"></div></div>""",
        unsafe_allow_html=True
    )

# ---------------------------
# View
# ---------------------------
def home():
    _inject_css()

    st.markdown('<div class="auth-wrap"><div class="auth-card">', unsafe_allow_html=True)
    st.markdown('<div class="brand"><span class="emoji">🔐</span><h1>Smart Inventory Manager</h1></div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">Sign in to continue, or create an account in seconds.</div>', unsafe_allow_html=True)

    tab_login, tab_register, tab_recover = st.tabs(["🔑 Login", "🆕 Register", "♻ Recover"])

    # -------- Login --------
    with tab_login:
        st.write("")
        phone = st.text_input("📱 Phone number", max_chars=20, key="login_phone")
        pw    = st.text_input("🔒 Password", type="password", key="login_pw")
        st.checkbox("Remember me", value=True, key="remember_me")
        if st.button("Login"):
            user = db.authenticate_user(phone, pw)
            if user:
                st.session_state["authenticated"] = True
                st.session_state["user_id"] = user[0]
                st.session_state["phone"]   = user[1]
                st.session_state["name"]    = user[2]
                st.session_state["just_logged_in"] = True  # App.py can route to main page
                st.success("Welcome back.")
                st.rerun()
            else:
                st.error("Invalid phone or password.")

    # -------- Register --------
    with tab_register:
        st.write("")
        c1, c2 = st.columns(2)
        with c1:
            phone_r = st.text_input("📱 Phone number", max_chars=20, key="reg_phone")
            name_r  = st.text_input("👤 Name", key="reg_name")
            pw_r    = st.text_input("🔒 Password", type="password", key="reg_pw")
        with c2:
            secret_q = st.text_input("❓ Secret question (for recovery)", key="reg_q")
            secret_a = st.text_input("📝 Secret answer", key="reg_a")
            if pw_r:
                score, label = _password_strength(pw_r)
                _strength_meter(score)
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
        if st.button("Find account", key="find_acc"):
            if not phone_f:
                st.error("Enter your phone number.")
            else:
                user = db.get_user_by_phone(phone_f)
                if user:
                    st.info(f"Secret question: {user[3] or '—'}")
                    ans   = st.text_input("📝 Your answer", key="rec_ans")
                    newpw = st.text_input("🔑 New password", type="password", key="rec_new")
                    if st.button("Reset password"):
                        if (ans or "").lower() == (user[4] or "").lower():
                            db.update_password_by_phone(phone_f, newpw)
                            st.success("Password updated. You can log in now.")
                        else:
                            st.error("Incorrect answer.")
                else:
                    st.error("No account with that phone.")

    st.markdown("</div></div>", unsafe_allow_html=True)
