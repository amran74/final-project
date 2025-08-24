# home.py — solid, reliable auth UI (no external assets, no overlay bugs)
import streamlit as st
from typing import Tuple
import db

st.set_page_config(page_title="Smart Inventory | Login", layout="wide")

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
# CSS + helpers
# ---------------------------
def _inject_css():
    st.markdown("""
    <style>
      :root {
        --accent: #2f6feb;
        --bg1: #0a1026;
        --bg2: #0f1a39;
      }

      /* Base background */
      .stApp {
        background: radial-gradient(1200px 600px at 15% 10%, var(--bg2), var(--bg1)) fixed !important;
      }

      /* Animated swirl lives BEHIND app via real element, not a pseudo-element */
      #bg-swirl {
        position: fixed;
        top: 0; left: 0; right: 0; bottom: 0;
        z-index: -1;                 /* keep background behind everything */
        background: conic-gradient(from 0deg at 50% 50%,
                    rgba(58,160,255,0.06),
                    rgba(18,22,41,0.0) 35%,
                    rgba(58,160,255,0.06) 70%,
                    rgba(18,22,41,0.0));
        animation: swirl 22s linear infinite;
        filter: blur(70px);
        pointer-events: none;
      }
      @keyframes swirl { 0% {transform:rotate(0deg)} 100% {transform:rotate(360deg)} }

      /* Layout */
      .auth-wrap { max-width: 1100px; margin: 5vh auto 7rem; padding: 0 16px; }
      .hero { display: grid; grid-template-columns: 1.2fr 1fr; gap: 26px; }
      @media (max-width: 980px) { .hero { grid-template-columns: 1fr; } }

      /* Card */
      .auth-card {
        background: rgba(18, 22, 41, 0.78);
        border: 1px solid rgba(65,108,181,0.28);
        backdrop-filter: blur(8px);
        border-radius: 22px;
        padding: 26px 26px 20px;
        box-shadow: 0 18px 50px rgba(0,0,0,0.35);
        position: relative;
      }
      .auth-card:after {
        content:"";
        position:absolute; inset:-2px; border-radius:24px; padding:1px;
        background: linear-gradient(180deg, var(--accent), rgba(255,255,255,0));
        -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
        -webkit-mask-composite: xor; mask-composite: exclude;
        opacity:.16; pointer-events:none;
      }

      .brand { display:flex; align-items:center; gap:14px; margin-bottom:2px; }
      .brand h1 { font-size:28px; color:#e9f2ff; margin:0; }
      .brand-sub { color:#9ab6d6; font-size:13px; margin: 2px 0 12px 46px; }

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
        border-radius: 12px; border:1px solid #27334f; background:#0f152c;
      }
      .stTextInput input, .stTextArea textarea { color:#e9f2ff; }
      .stTextInput>div>div:focus-within, .stPassword>div>div:focus-within, .stTextArea>div>div:focus-within {
        box-shadow: 0 0 0 2px var(--accent); border-color: var(--accent);
      }

      /* Buttons */
      .stButton>button {
        width:100%; height:44px; border-radius:12px;
        border: 1px solid rgba(31,59,106,0.9);
        background: linear-gradient(180deg,
          color-mix(in hsl, var(--accent) 92%, #fff 0%),
          color-mix(in hsl, var(--accent) 70%, #000 0%));
        color:#fff; font-weight:600;
        transition: transform .03s ease, filter .15s ease;
      }
      .stButton>button:active { transform: translateY(1px); }
      .stButton>button:hover { filter: brightness(1.05); }

      /* Right visual panel (SVG, no network dependency) */
      .art {
        background: rgba(18,22,41,0.55);
        border: 1px solid rgba(65,108,181,0.22);
        border-radius: 22px; padding: 14px;
        display:flex; align-items:center; justify-content:center;
        box-shadow: 0 14px 40px rgba(0,0,0,0.3);
        min-height: 100%;
      }
      .meter { height: 8px; border-radius: 999px; background:#172036; border:1px solid #24314b; }
      .meter > div { height: 100%; border-radius: 999px; }
    </style>
    <div id="bg-swirl"></div>
    """, unsafe_allow_html=True)

def _strength_meter(score: int):
    color = ["#e05252","#f2a93b","#e5d04a","#35c06d","#12d48b"][score]
    st.markdown(
        f"""<div class="meter"><div style="width:{(score/4)*100}%; background:{color}"></div></div>""",
        unsafe_allow_html=True
    )

# small inline SVG so the right side never breaks due to CORS/CDN
_DEF_SVG = """
<svg viewBox="0 0 540 360" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g1" x1="0" x2="1">
      <stop offset="0" stop-color="#2f6feb" stop-opacity="0.55"/>
      <stop offset="1" stop-color="#10b981" stop-opacity="0.55"/>
    </linearGradient>
    <linearGradient id="g2" x1="0" x2="1">
      <stop offset="0" stop-color="#1f2a48"/>
      <stop offset="1" stop-color="#0f162f"/>
    </linearGradient>
  </defs>
  <rect width="100%" height="100%" fill="url(#g2)"/>
  <g transform="translate(40,50)">
    <rect x="0" y="0" rx="16" ry="16" width="460" height="90" fill="url(#g1)"/>
    <rect x="18" y="25" rx="8" ry="8" width="180" height="14" fill="#cfe3ff" opacity="0.85"/>
    <rect x="18" y="50" rx="8" ry="8" width="260" height="10" fill="#9ab6d6" opacity="0.8"/>
  </g>
  <g transform="translate(40,170)">
    <rect x="0" y="0" rx="16" ry="16" width="220" height="140" fill="#15203c"/>
    <rect x="14" y="20" rx="6" ry="6" width="190" height="12" fill="#cfe3ff" opacity="0.85"/>
    <rect x="14" y="44" rx="6" ry="6" width="170" height="10" fill="#9ab6d6" opacity="0.8"/>
    <rect x="14" y="70" rx="6" ry="6" width="140" height="10" fill="#2f6feb" opacity="0.8"/>
  </g>
  <g transform="translate(280,170)">
    <rect x="0" y="0" rx="16" ry="16" width="220" height="140" fill="#15203c"/>
    <rect x="14" y="20" rx="6" ry="6" width="190" height="12" fill="#cfe3ff" opacity="0.85"/>
    <rect x="14" y="44" rx="6" ry="6" width="120" height="10" fill="#9ab6d6" opacity="0.8"/>
    <circle cx="180" cy="95" r="26" fill="url(#g1)" opacity="0.9"/>
  </g>
</svg>
"""

# ---------------------------
# View
# ---------------------------
def home():
    _inject_css()

    st.markdown('<div class="auth-wrap">', unsafe_allow_html=True)
    left, right = st.columns([1.15, 0.85], vertical_alignment="center")

    # ---- Left: Form card ----
    with left:
        st.markdown('<div class="auth-card">', unsafe_allow_html=True)

        header_l, header_r = st.columns([0.12, 0.88], vertical_alignment="center")
        with header_l:
            st.image("https://img.icons8.com/fluency/96/lock.png", width=42)  # tiny PNG, very stable CDN
        with header_r:
            st.markdown('<div class="brand"><h1>Smart Inventory Manager</h1></div>', unsafe_allow_html=True)
            st.markdown('<div class="brand-sub">Sign in to continue, or create an account in seconds.</div>', unsafe_allow_html=True)

        tab_login, tab_register, tab_recover = st.tabs(["🔑 Login", "🆕 Register", "♻ Recover"])

        # -------- Login --------
        with tab_login:
            st.write("")
            phone = st.text_input("📱 Phone number", max_chars=20, key="login_phone")
            pw = st.text_input("🔒 Password", type="password", key="login_pw")
            st.checkbox("Remember me", value=True, key="remember_me")
            if st.button("Login"):
                user = db.authenticate_user(phone, pw)
                if user:
                    st.session_state["authenticated"] = True
                    st.session_state["user_id"] = user[0]
                    st.session_state["phone"] = user[1]
                    st.session_state["name"] = user[2]
                    st.session_state["just_logged_in"] = True  # App.py listens for this
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
                if pw_r:
                    score, _ = _password_strength(pw_r)
                    _strength_meter(score)

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

        st.markdown("</div>", unsafe_allow_html=True)

    # ---- Right: Illustration (inline SVG, zero network failure) ----
    with right:
        st.markdown('<div class="art">', unsafe_allow_html=True)
        st.markdown(_DEF_SVG, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
