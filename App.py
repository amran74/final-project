# App.py — Smart Inventory Manager
# Clean routing + global KPI header (₪) shown on NON-home pages only.

from datetime import date, timedelta
from pathlib import Path
import importlib, importlib.util
import traceback
import streamlit as st

st.set_page_config(page_title="Smart Inventory Manager", page_icon="🍴", layout="wide")

# -----------------------------------------------------------------------------
# Diagnostics
# -----------------------------------------------------------------------------
IMPORT_ERRORS = {}

def _record_error(name: str, err: BaseException):
    IMPORT_ERRORS[name] = f"{type(err).__name__}: {err}\n" + traceback.format_exc()

# -----------------------------------------------------------------------------
# Import helpers
# -----------------------------------------------------------------------------
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
    for pat in patterns:
        for py in sorted(here.glob(pat)):
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

# -----------------------------------------------------------------------------
# KPI source (dashboards_core) with safe fallback
# -----------------------------------------------------------------------------
try:
    from dashboards_core import TODAY, kpis_for_window, expiring_soon
except Exception:
    TODAY = date.today()
    def kpis_for_window(*_, **__):
        return {
            "waste_total": 0.0,
            "waste_vs_spend": None,
            "waste_vs_inventory": None,
            "waste_per_day": 0.0,
            "spend_total": 0.0,
            "wow": None,
            "mom": None,
            "expiring_items": 0,
            "expiring_value": 0.0,
            "inventory_value": 0.0,
        }
    def expiring_soon(*_, **__):
        return 0, 0.0

# -----------------------------------------------------------------------------
# Load pages
# -----------------------------------------------------------------------------
home = _find_first_available(("home",), ("home",), ("home.py",))
calendar_view = _find_first_available(("calendar_view","render","app"), ("CalendarView",), ("CalendarView.py",))
inventory = _find_first_available(("inventory",), ("Inventory","inventory"), ("Inventory.py","inventory.py"))
shopping_page = _find_first_available(("shopping",), ("Shopping","shopping"), ("Shopping.py","shopping.py"))
coach = _find_first_available(("coach",), ("SmartCoach",), ("SmartCoach.py","coach.py"))
recipes = _find_first_available(("recipes_page","render"), ("RecipesPage",), ("RecipesPage.py","recipes.py"))
dashboard = _find_first_available(("dashboard",), ("dashboard",), ("dashboard.py",))

# -----------------------------------------------------------------------------
# DB setup (safe)
# -----------------------------------------------------------------------------
def _safe_db_setup():
    try:
        from db import create_tables, reset_monthly_counters
        create_tables(); reset_monthly_counters()
        return True
    except Exception as e:
        _record_error("db.init", e); return False

_db_ready = _safe_db_setup()

# -----------------------------------------------------------------------------
# Small UX helpers
# -----------------------------------------------------------------------------
def _user_name() -> str:
    return (
        st.session_state.get("name")
        or st.session_state.get("user_name")
        or st.session_state.get("phone")
        or "User"
    )

def _inject_top_css():
    st.markdown(
        """
        <style>
          .app-kpi-row { margin-top: -8px; }
          .app-kpi-row .stMetric {
              background: rgba(16,24,51,.55);
              border: 1px solid #22325a;
              border-radius: 14px;
              padding: 10px 12px;
          }
          .app-sep { margin: 8px 0 10px; border-top: 1px solid #1e2a44; }
        </style>
        """,
        unsafe_allow_html=True,
    )

# -----------------------------------------------------------------------------
# Auth gate
# -----------------------------------------------------------------------------
st.session_state.setdefault("authenticated", False)

if not st.session_state.get("authenticated"):
    if callable(home): home()
    else:
        st.title("Smart Inventory Manager")
        st.error("Login page not available: expected home.py with home().")
    st.stop()

# -----------------------------------------------------------------------------
# Page registry (sidebar order)
# -----------------------------------------------------------------------------
PAGES = {}
if callable(calendar_view): PAGES["🏡 Home"] = calendar_view
elif callable(home): PAGES["🏡 Home"] = home
if callable(inventory): PAGES["📦 Stock"] = inventory
if callable(shopping_page): PAGES["🛒 Shopping"] = shopping_page
if callable(coach): PAGES["🧠 Coach"] = coach
if callable(recipes): PAGES["🍽️ Recipes"] = recipes
if callable(dashboard): PAGES["📊 Stats"] = dashboard

# -----------------------------------------------------------------------------
# Sidebar
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("🍴 Smart Inventory")
    name_display = (_user_name().split()[0].capitalize() if _user_name() else "User")
    st.caption(f"Signed in as **{name_display}**")

    choice = st.radio("Navigate", list(PAGES.keys()) if PAGES else ["(no pages)"])
    page_fn = PAGES.get(choice)

    st.markdown("---")
    if st.button("🔐 Logout"):
        for k in ["authenticated","user_id","phone","name","user_name"]:
            st.session_state.pop(k, None)
        st.rerun()

    with st.expander("Advanced ▸ Diagnostics", expanded=False):
        st.write("**Loaded pages**")
        for name in PAGES.keys(): st.write("•", name)
        if IMPORT_ERRORS:
            st.write("**Import issues**")
            for name, err in IMPORT_ERRORS.items():
                st.markdown(f"- **{name}** failed")
                st.code(err or "Unknown error", language="text")
        else:
            st.caption("No import errors recorded.")

# -----------------------------------------------------------------------------
# Global KPI header — SHOW ONLY ON NON-HOME PAGES
# -----------------------------------------------------------------------------
_inject_top_css()

uid = st.session_state.get("user_id")
is_home = (page_fn is calendar_view) or (page_fn is home)

if uid and not is_home:
    start = TODAY - timedelta(days=30)
    end = TODAY
    k = kpis_for_window(int(uid), start, end)
    exp_ct, exp_val = expiring_soon(int(uid), 7)

    st.markdown('<div class="app-kpi-row">', unsafe_allow_html=True)
    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.metric("Inventory value", f"₪{float(k.get('inventory_value') or 0):,.0f}")
    c2.metric("Spend 30d", f"₪{float(k.get('spend_total') or 0):,.0f}")
    c3.metric("Waste 30d", f"₪{float(k.get('waste_total') or 0):,.0f}")
    wvs = k.get("waste_vs_spend")
    if wvs is not None:
        c4.metric("Waste vs Spend", f"{float(wvs):.1f}%")
    else:
        c4.metric("Waste vs Spend", "—")
    c5.metric("Expiring ≤7d (items)", f"{int(exp_ct or 0)}")
    c6.metric("Expiring ≤7d (₪)", f"₪{float(exp_val or 0):,.0f}")
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown('<div class="app-sep"></div>', unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# Render selected page
# -----------------------------------------------------------------------------
if PAGES:
    try:
        page_fn()
    except Exception:
        st.error(f"Page **{choice}** failed to load.")
        with st.expander("Show error details"):
            st.code(traceback.format_exc(), language="text")
else:
    st.error("No pages are available. Check diagnostics in the sidebar.")

st.caption(f"{date.today().isoformat()} • {choice}")
