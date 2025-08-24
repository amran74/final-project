# home.py — split-screen hero + right-side login card (no scroll, no flakes)
import streamlit as st
from typing import Tuple
import db

st.set_page_config(page_title="Smart Inventory | Sign in", page_icon="🔐", layout="wide")

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
      :root{
        --bg1:#0b1220;
        --bg2:#0f172a;
        --panel:#121a33cc;      /* glassy */
        --border:#5a6db34a;
        --accent:#3b82f6;
        --text:#eaf1ff;
        --muted:#9db4d4;
        --input:#0f1731;
      }

      /* Remove Streamlit's huge top padding and pin content in viewport */
      .block-container{
        padding-top: 1.25rem !important;
        padding-bottom: 1.25rem !important;
      }
      .stApp{
        background: radial-gradient(1100px 600px at 20% 10%, var(--bg2), var(--bg1)) fixed !important;
      }

      /* Full-height split hero (no scrolling needed) */
      .hero{
        min-height: calc(100vh - 2.5rem);
        display: grid;
        grid-template-columns: 1.1fr 0.9fr;
        gap: 32px;
        align-items: center;         /* vertical center */
      }
      @media (max-width: 1100px){
        .hero{ grid-template-columns: 1fr; padding-top: .5rem; padding-bottom: 1rem; }
      }

      /* Left visual panel */
      .visual{
        background: linear-gradient(180deg, #0f1b3b, #0d1730);
        border: 1px solid #2b3b66;
        border-radius: 22px;
        padding: 28px;
        box-shadow: 0 18px 50px rgba(0,0,0,.35);
      }
      .visual h1{
        margin: 0 0 10px 0;
        font-size: 40px;
        color: var(--text);
        letter-spacing: .3px;
      }
      .visual p{
        margin: 0 0 22px 0;
        color: var(--muted);
        font-size: 16px;
      }
      /* Inline SVG "illustration" that always loads */
      .visual .art{
        width: 100%;
        border-radius: 16px;
        overflow: hidden;
        border: 1px solid #32446f;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.04);
      }

      /* Right login card */
      .card{
        background: var(--panel);
        border: 1px solid var(--border);
        backdrop-filter: blur(8px);
        border-radius: 20px;
        padding: 22px 22px 18px;
        box-shadow: 0 18px 50px rgba(0,0,0,.35);
        position: relative;
      }
      .card:after{
        content:""; position:absolute; inset:-2px; padding:1px; border-radius:22px;
        background: linear-gradient(180deg, var(--accent), rgba(255,255,255,0));
        -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
        -webkit-mask-composite:xor; mask-composite:exclude; opacity:.14; pointer-events:none;
      }

      .brand{ display:flex; align-items:center; gap:10px; margin-bottom:4px; }
      .brand .emoji{ font-size: 24px; }
      .brand h2{ margin:0; color:var(--text); font-size:24px; letter-spacing:.2px; }
      .sub{ color:var(--muted); font-size:13px; margin:2px 0 12px 34px; }

      /* Tabs */
      .stTabs [data-baseweb="tab-list"]{ gap:6px; }
      .stTabs [data-baseweb="tab"]{
        background:#0f152c; color:#cfe3ff; border-radius:12px 12px 0 0;
        padding:8px 14px; border:1px solid #1e2a44;
      }
      .stTabs [aria-selected="true"]{
        background:#0e2442; border-color:var(--accent); color:#e9f6ff;
      }

      /* Inputs */
      .stTextInput>div>div, .stPassword>div>div, .stTextArea>div>div{
        border-radius:12px; border:1px solid #27334f; background:var(--input);
      }
      .stTextInput input, .stTextArea textarea{ color:var(--text); }
      .stTextInput>div>div:focus-within,
      .stPassword>div>div:focus-within,
      .stTextArea>div>div:focus-within{
        box-shadow:0 0 0 2px var(--accent); border-color:var(--accent);
      }

      /* Buttons */
      .stButton>button{
        width:100%; height:44px; border-radius:12px;
        border:1px solid rgba(31,59,106,.9);
        background: linear-gradient(180deg,#4b8bf7,#2f6feb);
        color:#fff; font-weight:600;
        transition: transform .03s ease, filter .15s ease;
      }
      .stButton>button:active{ transform: translateY(1px); }
      .stButton>button:hover{ filter:brightness(1.05); }

      /* Strength meter */
      .meter{ height:8px; border-radius:999px; background:#172036; border:1px solid #24314b; }
      .meter>div{ height:100%; border-radius:999px; }
    </style>
    """, unsafe_allow_html=True)

def _strength_meter(score:int):
    color = ["#e05252","#f2a93b","#e5d04a","#35c06d","#12d48b"][score]
    st.markdown(f'<div class="meter"><div style="width:{(score/4)*100}%;background:{color}"></div></div>',
                unsafe_allow_html=True)

# Simple inline SVG that always renders (no network)
_HERO_SVG = """
<svg viewBox="0 0 800 380" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g1" x1="0" x2="1">
      <stop offset="0" stop-color="#3b82f6"/>
      <stop offset="1" stop-color="#10b981"/>
    </linearGradient>
  </defs>
  <rect width="800" height="380" fill="#0f1936"/>
  <g opacity=".95">
    <rect x="40" y="40" rx="18" ry="18" width="720" height="96" fill="url(#g1)"/>
    <rect x="70" y="74" rx="6" ry="6" width="280" height="14" fill="#e9f2ff" opacity=".9"/>
    <rect x="70" y="98" rx="6" ry="6" width="380" height="10" fill="#cfe3ff" opacity=".8"/>
  </g>
  <g opacity=".92">
    <rect x="40" y="168" rx="18" ry="18" width="340" height="160" fill="#142041"/>
    <rect x="60" y="198" rx="6" ry="6" width="220" height="12" fill="#e9f2ff" opacity=".85"/>
    <rect x="60" y="222" rx="6" ry="6" width="200" height="10" fill="#9ab6d6" opacity=".8"/>
    <rect x="60" y="248" rx="6" ry="6" width="170" height="10" fill="#3b82f6" opacity=".85"/>
  </g>
  <g opacity=".92">
    <rect x="420" y="168" rx="18" ry="18" width="340" height="160" fill="#142041"/>
    <rect x="442" y="198" rx="6" ry="6" width="220" height="12" fill="#e9f2ff" opacity=".85"/>
    <rect x="442" y="222" rx="6" ry="6" width="160" height="10" fill="#9ab6d6" opacity=".8"/>
    <circle cx="708" cy="280" r="28" fill="url(#g1)"/>
  </g>
</svg>
"""

# ---------------------------
# View
# ---------------------------
def home():
    _inject_css()

    # Split hero (left illustration, right auth card)
    col_left, col_right = st.columns([1.1, 0.9], vertical_alignment="center")
    with col_left:
        st.markdown("""
          <div class="hero">
            <div class="visual">
              <h1>Smart Inventory Manager</h1>
              <p>Track stock, place orders, and stay on top of your business. Fast. Simple. Accurate.</p>
              <div class="art">""" + _HERO_SVG + """</div>
            </div>
          </div>
        """, unsafe_allow_html=True)

    with col_right:
        st.markdown('<div class="hero"><div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="brand"><span class="emoji">🔐</span><h2>Welcome back</h2></div>', unsafe_allow_html=True)
        st.markdown('<div class="sub">Sign in, or create an account in seconds.</div>', unsafe_allow_html=True)

        tab_login, tab_register, tab_recover = st.tabs(["🔑 Login", "🆕 Register", "♻ Recover"])

        # ---------- Login ----------
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
                    st.session_state["just_logged_in"] = True
                    st.success("Welcome back.")
                    st.rerun()
                else:
                    st.error("Invalid phone or password.")

        # ---------- Register ----------
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

        # ---------- Recover ----------
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

        st.markdown('</div></div>', unsafe_allow_html=True)
