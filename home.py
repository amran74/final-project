# home.py — lively auth screen (animated bg, hero image, per-tab accents)
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
# CSS + helpers
# ---------------------------
def _inject_css(accent="#2f6feb"):
    st.markdown(f"""
    <style>
      :root {{
        --accent: {accent};
        --bg1: #0a1026;
        --bg2: #0f1a39;
      }}

      /* Animated background */
      .stApp {{
        background: radial-gradient(1200px 600px at 15% 10%, var(--bg2), var(--bg1)) fixed;
        position: relative;
        overflow: hidden;
      }}
      .stApp:before {{
        content: "";
        position: fixed; inset: -40%;
        background: conic-gradient(from 0deg at 50% 50%, rgba(58,160,255,0.10), rgba(18,22,41,0.0) 35%, rgba(58,160,255,0.10) 70%, rgba(18,22,41,0.0));
        animation: swirl 18s linear infinite;
        filter: blur(60px);
        pointer-events: none;
      }}
      @keyframes swirl {{ 0%{{transform:rotate(0deg)}} 100%{{transform:rotate(360deg)}} }}

      /* Hero container */
      .auth-wrap {{ max-width: 1100px; margin: 5vh auto 7rem; padding: 0 16px; }}
      .hero {{
        display: grid;
        grid-template-columns: 1.2fr 1fr;
        gap: 26px;
      }}
      @media (max-width: 980px) {{
        .hero {{ grid-template-columns: 1fr; }}
      }}

      /* Card left */
      .auth-card {{
        background: rgba(18, 22, 41, 0.78);
        border: 1px solid rgba(65,108,181,0.28);
        backdrop-filter: blur(8px);
        border-radius: 22px;
        padding: 26px 26px 20px;
        box-shadow: 0 18px 50px rgba(0,0,0,0.35);
        position: relative;
      }}

      /* Accent glow ring */
      .auth-card:after {{
        content:"";
        position:absolute; inset:-2px;
        border-radius:24px;
        padding:1px;
        background: linear-gradient(180deg, var(--accent), rgba(255,255,255,0));
        -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
        -webkit-mask-composite: xor; mask-composite: exclude;
        opacity:.18;
        pointer-events:none;
      }}

      /* Header shimmer bar */
      .shimmer {{
        height: 12px; border-radius: 999px; width: 85%;
        background: linear-gradient(90deg, rgba(255,255,255,0.05), rgba(255,255,255,0.12), rgba(255,255,255,0.05));
        background-size: 200% 100%;
        animation: shine 3s ease-in-out infinite;
        margin-bottom: 18px;
      }}
      @keyframes shine {{ 0% {{background-position:200% 0}} 100% {{background-position:-200% 0}} }}

      .brand {{ display:flex; align-items:center; gap:14px; margin-bottom:6px; }}
      .brand h1 {{ font-size:28px; color:#e9f2ff; margin:0; letter-spacing:.2px; }}
      .brand-sub {{ color:#9ab6d6; font-size:13px; margin:4px 0 14px 46px; }}

      /* Tabs */
      .stTabs [data-baseweb="tab-list"] {{ gap: 6px; }}
      .stTabs [data-baseweb="tab"] {{
        background: #0f152c; color:#cfe3ff; border-radius:12px 12px 0 0;
        padding: 8px 14px; border:1px solid #1e2a44;
      }}
      .stTabs [aria-selected="true"] {{
        background: #0e2442; border-color: var(--accent); color:#e9f6ff;
      }}

      /* Inputs */
      .stTextInput>div>div, .stPassword>div>div, .stTextArea>div>div {{
        border-radius: 12px; border:1px solid #27334f; background:#0f152c;
      }}
      .stTextInput input, .stTextArea textarea {{ color:#e9f2ff; }}
      .stTextInput>div>div:focus-within, .stPassword>div>div:focus-within, .stTextArea>div>div:focus-within {{
        box-shadow: 0 0 0 2px var(--accent);
        border-color: var(--accent);
      }}

      /* Buttons */
      .stButton>button {{
        width:100%; height:44px; border-radius:12px;
        border: 1px solid rgba(31,59,106,0.9);
        background: linear-gradient(180deg, color-mix(in hsl, var(--accent) 92%, #fff 0%), color-mix(in hsl, var(--accent) 70%, #000 0%));
        color:#fff; font-weight:600;
        transition: transform .03s ease, filter .15s ease;
      }}
      .stButton>button:active {{ transform: translateY(1px); }}
      .stButton>button:hover {{ filter: brightness(1.05); }}

      /* Right illustration card */
      .art {{
        background: rgba(18,22,41,0.55);
        border: 1px solid rgba(65,108,181,0.22);
        border-radius: 22px; padding: 14px;
        display:flex; align-items:center; justify-content:center;
        box-shadow: 0 14px 40px rgba(0,0,0,0.3);
      }}
      .art img {{
        width: 100%; border-radius: 16px;
        box-shadow: 0 10px 28px rgba(0,0,0,0.35);
      }}

      /* Rows */
      .row {{ display:flex; gap:12px; }}
      .col {{ flex:1; }}

      /* Strength bar */
      .meter {{ height: 8px; border-radius: 999px; background:#172036; border:1px solid #24314b; }}
      .meter > div {{ height: 100%; border-radius: 999px; }}

    </style>
    """, unsafe_allow_html=True)

def _strength_meter(score: int):
    # color per score
    color = ["#e05252","#f2a93b","#e5d04a","#35c06d","#12d48b"][score]
    st.markdown(
        f"""<div class="meter"><div style="width:{(score/4)*100}%; background:{color}"></div></div>""",
        unsafe_allow_html=True
    )

# ---------------------------
# View
# ---------------------------
def home():
    # default accent
    _inject_css("#2f6feb")
    st.markdown('<div class="auth-wrap">', unsafe_allow_html=True)

    left, right = st.columns([1.15, 0.85], vertical_alignment="center")

    with left:
        st.markdown('<div class="auth-card">', unsafe_allow_html=True)
        st.markdown('<div class="shimmer"></div>', unsafe_allow_html=True)

        header_l, header_r = st.columns([0.12, 0.88], vertical_alignment="center")
        with header_l:
            st.image("https://img.icons8.com/fluency/96/lock.png", width=42)
        with header_r:
            st.markdown('<div class="brand"><h1>Smart Inventory Manager</h1></div>', unsafe_allow_html=True)
            st.markdown('<div class="brand-sub">Sign in to continue, or create an account in seconds.</div>', unsafe_allow_html=True)

        tab_login, tab_register, tab_recover = st.tabs(["🔑 Login", "🆕 Register", "♻ Recover"])

        # -------- Login (accent blue) --------
        with tab_login:
            _inject_css("#2f6feb")
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
                    st.session_state["just_logged_in"] = True
                    st.success("Welcome back.")
                    st.rerun()
                else:
                    st.error("Invalid phone or password.")

        # -------- Register (accent green) --------
        with tab_register:
            _inject_css("#10b981")
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

        # -------- Recover (accent amber) --------
        with tab_recover:
            _inject_css("#f59e0b")
            st.write("")
            phone_f = st.text_input("📱 Phone number", key="rec_phone")
            find = st.button("Find account", key="find_acc")
            if find:
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

    with right:
        # Illustration: pick any public image you like; this one is neutral and clean.
        st.markdown('<div class="art">', unsafe_allow_html=True)
        st.image(
            "https://images.unsplash.com/photo-1557825835-70d97c4aa067?q=80&w=1600&auto=format&fit=crop",  # keyboard/workspace aesthetic
            use_container_width=True
        )
        st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)
