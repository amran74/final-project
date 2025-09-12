# App.py — Smart Inventory Manager (modernized)
from datetime import date
import traceback
import importlib, importlib.util
from pathlib import Path
import streamlit as st

st.set_page_config(page_title="Smart Inventory Manager", page_icon="🍴", layout="wide")

# ---------- Diagnostics store ----------
IMPORT_ERRORS = {}

def _record_error(name: str, err: BaseException):
    IMPORT_ERRORS[name] = f"{type(err).__name__}: {err}\n" + traceback.format_exc()

# ---------- Robust import helpers ----------
def _import_attr(module_name: str, attr_name: str):
    try:
        mod = importlib.import_module(module_name)
        return getattr(mod, attr_name)
    except Exception as e:
        _record_error(f"{module_name}.{attr_name}", e)
        return None

def _import_attr_from_file(pyfile: Path, attr_name: str):
    try:
        unique_name = f"_dyn_{pyfile.stem}"
        spec = importlib.util.spec_from_file_location(unique_name, str(pyfile))
        if not spec or not spec.loader:
            raise ImportError(f"Cannot build spec for {pyfile}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[attr-defined]
        return getattr(mod, attr_name)
    except Exception as e:
        _record_error(f"{pyfile.name}.{attr_name}", e)
        return None

def _find_and_load_page(attr_name: str, preferred_modules=(), filename_patterns=()):
    for mod in preferred_modules:
        fn = _import_attr(mod, attr_name)
        if callable(fn):
            return fn
    here = Path(__file__).resolve().parent
    patterns = filename_patterns or (f"{attr_name}.py", f"{attr_name.lower()}.py")
    candidates = []
    for pat in patterns:
        candidates.extend(sorted(here.glob(pat)))
    for py in candidates:
        fn = _import_attr_from_file(py, attr_name)
        if callable(fn):
            return fn
    return None

def _find_first_available(attr_names, preferred_modules=(), filename_patterns=()):
    for attr in attr_names:
        fn = _find_and_load_page(attr, preferred_modules, filename_patterns)
        if callable(fn):
            return fn
    return None

# ---------- Load pages ----------
home = _find_first_available(("home",), ("home",), ("home.py",))
calendar_view = _find_first_available(("calendar_view",), ("CalendarView",), ("CalendarView.py",))
inventory = _find_first_available(("inventory",), ("Inventory","inventory"), ("Inventory.py","inventory.py"))
shopping_page = _find_first_available(("shopping",), ("Shopping","shopping"), ("Shopping.py","shopping.py"))
coach = _find_first_available(("coach",), ("SmartCoach",), ("SmartCoach.py","coach.py"))
recipes = _find_first_available(("recipes_page","render"), ("RecipesPage",), ("RecipesPage.py","recipes.py"))
dashboard = _find_first_available(("dashboard",), ("dashboard",), ("dashboard.py",))
# Freeze AI page for now
# ai_assistant = _find_first_available(("ai_assistant",), ("AI_Assistant",), ("AI_Assistant.py","ai_assistant.py"))

# ---------- DB helpers ----------
def _safe_db_setup():
    try:
        from db import create_tables, reset_monthly_counters
        create_tables(); reset_monthly_counters()
        return True
    except Exception as e:
        _record_error("db.init", e); return False

def _safe_kpis(user_id: int):
    try:
        from db import get_connection, get_monthly_summary
        conn = get_connection(); c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM inventory WHERE user_id=?", (user_id,))
        total_items = c.fetchone()[0] or 0
        ms = get_monthly_summary(user_id); conn.close()
        return total_items, ms.get("used_steps",0), ms.get("expired_steps",0), float(ms.get("money_lost",0.0))
    except Exception as e:
        _record_error("db.kpis", e); return 0,0,0,0.0

_db_ready = _safe_db_setup()

# ---------- Helpers ----------
def _user_name() -> str:
    return st.session_state.get("name") or st.session_state.get("phone") or "User"

st.session_state.setdefault("authenticated", False)

# ---------- Auth gate ----------
if not st.session_state.get("authenticated"):
    if callable(home): home()
    else:
        st.title("Smart Inventory Manager")
        st.error("Login page not available: make sure home.py defines home().")
    st.stop()

# ---------- Page registry ----------
PAGES = {}
if callable(calendar_view): PAGES["🏡 Home"] = calendar_view
elif callable(home): PAGES["🏡 Home"] = home
if callable(inventory): PAGES["📦 Stock"] = inventory
if callable(shopping_page): PAGES["🛒 Shopping"] = shopping_page
if callable(coach): PAGES["🧠 Coach"] = coach
if callable(recipes): PAGES["🍽️ Recipes"] = recipes
if callable(dashboard): PAGES["📊 Stats"] = dashboard
# if callable(ai_assistant): PAGES["🤖 AI"] = ai_assistant

# ---------- Sidebar ----------
with st.sidebar:
    st.title("🍴 Smart Inventory")
    st.caption(f"Signed in as **{_user_name()}**")

    choice = st.radio("Navigate", list(PAGES.keys()) if PAGES else ["(no pages)"])

    st.markdown("---")
    if st.button("🔐 Logout"):
        for k in ["authenticated","user_id","phone","name"]:
            st.session_state.pop(k, None)
        st.rerun()

    with st.expander("Advanced ▸ Diagnostics", expanded=False):
        st.write("**Loaded pages**")
        for name in PAGES.keys():
            st.write("•", name)
        if IMPORT_ERRORS:
            st.write("**Import issues**")
            for name, err in IMPORT_ERRORS.items():
                st.markdown(f"- **{name}** failed")
                st.code(err or "Unknown error", language="text")
        else:
            st.caption("No import errors recorded.")

# ---------- KPI header ----------
st.markdown(f"### 👋 Welcome back, {_user_name()}  —  {date.today().strftime('%A, %d %B %Y')}")
uid = st.session_state.get("user_id")
items, used, expired, lost = _safe_kpis(uid) if uid else (0,0,0,0.0)

c1,c2,c3,c4 = st.columns(4)
c1.metric("📦 Items", items)
c2.metric("✅ Used (mo)", used)
c3.metric("⛔ Expired (mo)", expired)
c4.metric("💸 Money lost (mo)", f"{lost:.2f}")

st.markdown("---")

# ---------- Render selected page ----------
if PAGES:
    try:
        PAGES[choice]()
    except Exception:
        st.error(f"Page **{choice}** failed to load.")
        with st.expander("Show error details"):
            st.code(traceback.format_exc(), language="text")
else:
    st.error("No pages are available. Check diagnostics in the sidebar.")

st.markdown("---")
st.caption(f"{date.today().isoformat()} • {choice}")
