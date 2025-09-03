# home.py — clean split layout, zero weird top gap
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
    return score, labels[min(score, 4)]

# ---------------------------
# CSS — trim top padding, style panels
# ---------------------------
def _inject_css():
    st.markdown("""
    <style>
      :root{
        --bg1:#090e21; --bg2:#0f1733; --panel:#101833e6; --border:#24365a;
        --accent:#3b82f6; --text:#eaf1ff; --muted:#9fb1d2; --input:#0f1731;
      }
      .stApp{
        background: radial-gradient(1200px 600px at 12% 12%, var(--bg2), var(--bg1)) fixed !important;
      }
      /* Cut default Streamlit top padding without breaking toolbar */
      .block-container{ padding-top: 8px !important; padding-bottom: 16px !important; }

      /* hero panel */
      .hero{
        background: linear-gradient(180deg, #0f1630, #0b1126);
        border:1px solid #1b2a4d; border-radius:18px; padding:24px 26px;
        box-shadow: 0 18px 50px rgba(0,0,0,.35);
      }
      .hero h1{ color:var(--text); margin:0 0 6px; font-size:30px; letter-spacing:.2px; }
      .hero p{ color:var(--muted); margin:0 0 18px; }
      .hero .mock{
        border:1px solid #223257; background:#0e1531; border-radius:14px; padding:16px;
        height: 220px; display:grid; grid-template-rows: 48px 1fr; gap:12px;
      }
      .bar{ height:12px; border-radius:10px; background:#1b2646; }
      .bar.accent{ background: linear-gradient(90deg,#4b8bf7,#2f6feb); }
      .bullet{ display:flex; gap:10px; align-items:flex-start; color:#cfe3ff; margin:6px 0; }
      .dot{ width:8px; height:8px; border-radius:999px; background:#59a2ff; margin-top:7px; }

      /* auth card */
      .auth-card{
        background: var(--panel); border: 1px solid var(--border); border-radius: 18px;
        padding: 22px 22px 18px; backdrop-filter: blur(8px);
        box-shadow: 0 18px 50px rgba(0,0,0,.35); position: relative;
      }
      .auth-card:after{
        content:""; position:absolute; inset:-2px; padding:1px; border-radius:20px;
        background: linear-gradient(180deg, var(--accent), rgba(255,255,255,0));
        -webkit-mask:linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
        -webkit-mask-composite:xor; mask-composite:exclude; opacity:.12; pointer-events:none;
      }
      .brand{ display:flex; align-items:center; gap:10px; margin-bottom:6px; }
      .brand .emoji{ font-size: 22px; }
      .brand h2{ font-size: 22px; margin:0; color:var(--text); letter-spacing:.2px; }
      .brand-sub{ margin:2px 0 12px 32px; color:var(--muted); font-size:13px; }

      /* tabs + inputs */
      .stTabs [data-baseweb="tab-list"]{ gap:6px; }
      .stTabs [data-baseweb="tab"]{ background:#0f152c; color:#cfe3ff; border-radius:12px 12px 0 0;
                                    padding:8px 14px; border:1px solid #1e2a44; }
      .stTabs [aria-selected="true"]{ background:#0e2442; border-color:var(--accent); color:#e9f6ff; }
      .stTextInput>div>div, .stPassword>div>div, .stTextArea>div>div{
        border-radius:12px; border:1px solid #27334f; background:var(--input);
      }
      .stTextInput input, .stTextArea textarea{ color:#eaf1ff; }
      .stTextInput>div>div:focus-within, .stPassword>div>div:focus-within, .stTextArea>div>div:focus-within{
        box-shadow:0 0 0 2px var(--accent); border-color:var(--accent);
      }
      .stButton>button{
        width:100%; height:44px; border-radius:12px;
        border:1px solid rgba(31,59,106,.9);
        background: linear-gradient(180deg,#4b8bf7,#2f6feb);
        color:#fff; font-weight:600; transition: transform .03s ease, filter .15s ease;
      }
      .stButton>button:active{ transform: translateY(1px); }
      .stButton>button:hover{ filter: brightness(1.05); }

      .meter{ height:8px; border-radius:999px; background:#172036; border:1px solid #24314b; }
      .meter>div{ height:100%; border-radius:999px; }
    </style>
    """, unsafe_allow_html=True)

def _strength_meter(score:int):
    color = ["#e05252","#f2a93b","#e5d04a","#35c06d","#12d48b"][min(score,4)]
    st.markdown(f'<div class="meter"><div style="width:{(min(score,4)/4)*100}%;background:{color}"></div></div>',
                unsafe_allow_html=True)

# ---------------------------
# View
# ---------------------------
def home():
    _inject_css()

    # Use native Streamlit columns (no vertical_alignment)
    left, right = st.columns([1.15, 1.0])

    with left:
        st.markdown(
            """
            <div class="hero">
              <h1>Smart Inventory Manager</h1>
              <p>Track stock, avoid waste, and keep costs under control. Fast. Simple. Accurate.</p>
              <div class="mock">
                <div class="bar accent"></div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                  <div style="background:#0c142f; border:1px solid #21325a; border-radius:12px; padding:12px;">
                    <div class="bar" style="width:78%; margin-bottom:10px;"></div>
                    <div class="bar" style="width:56%;"></div>
                  </div>
                  <div style="background:#0c142f; border:1px solid #21325a; border-radius:12px; padding:12px;">
                    <div class="bar" style="width:64%; margin-bottom:10px;"></div>
                    <div class="bar" style="width:42%;"></div>
                  </div>
                </div>
              </div>
              <div style="margin-top:16px;">
                <div class="bullet"><div class="dot"></div><div>Clean login and secure user accounts.</div></div>
                <div class="bullet"><div class="dot"></div><div>Per-item tracking, stability flags, and usage analytics.</div></div>
                <div class="bullet"><div class="dot"></div><div>Calendar view and dashboards that don’t make your eyes cry.</div></div>
              </div>
            </div>
            """,
            unsafe_allow_html=True
        )

    with right:
        st.markdown('<div class="auth-card">', unsafe_allow_html=True)
        st.markdown('<div class="brand"><span class="emoji">🔐</span><h2>Welcome back</h2></div>', unsafe_allow_html=True)
        st.markdown('<div class="brand-sub">Sign in or create an account in seconds.</div>', unsafe_allow_html=True)

        tab_login, tab_register, tab_recover = st.tabs(["🔑 Login", "🆕 Register", "♻ Recover"])

        # Login
        with tab_login:
            with st.form("login_form", clear_on_submit=False):
                phone = st.text_input("📱 Phone number", max_chars=20, key="login_phone")
                pw    = st.text_input("🔒 Password", type="password", key="login_pw")
                st.checkbox("Remember me", value=True, key="remember_me")
                submitted = st.form_submit_button("Login")
            if submitted:
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

        # Register
        with tab_register:
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
            if st.button("Register", disabled=not agree, key="register_btn"):
                if not phone_r or not pw_r or not name_r:
                    st.error("Please fill in all required fields.")
                else:
                    ok = db.create_user(phone_r, pw_r, name_r, secret_q, secret_a)
                    if ok:
                        st.success("Account created. You can now log in.")
                    else:
                        st.error("Phone number already exists.")

        # Recover
        with tab_recover:
            phone_f = st.text_input("📱 Phone number", key="rec_phone")
            if st.button("Find account", key="find_acc"):
                if not phone_f:
                    st.error("Enter your phone number.")
                else:
                    user = db.get_user_by_phone(phone_f)
                    if user:
                        st.session_state["recovery"] = {
                            "phone": phone_f,
                            "q": (user[3] if len(user) > 3 and user[3] else "—"),
                            "a": (user[4] if len(user) > 4 and user[4] else "")
                        }
                    else:
                        st.error("No account with that phone.")

            rec = st.session_state.get("recovery")
            if rec:
                st.info(f"Secret question: {rec['q']}")
                ans   = st.text_input("📝 Your answer", key="rec_ans")
                newpw = st.text_input("🔑 New password", type="password", key="rec_new")
                if st.button("Reset password", key="reset_pw"):
                    if (ans or "").strip().lower() == (rec["a"] or "").strip().lower():
                        db.update_password_by_phone(rec["phone"], newpw)
                        st.success("Password updated. You can log in now.")
                        st.session_state.pop("recovery", None)
                    else:
                        st.error("Incorrect answer.")

        st.markdown('</div>', unsafe_allow_html=True)  # close auth-card

if __name__ == "__main__":
    home()
