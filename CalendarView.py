# CalendarView.py — Premium info-only Home Dashboard (no actions)
import streamlit as st
from datetime import date, datetime, timedelta
from streamlit_calendar import calendar
import db

# Optional AI tips (safe fallback if not configured)
try:
    import openai  # type: ignore
    _AI_OK = True
except Exception:
    _AI_OK = False

# ========= CONFIG =========
CALENDAR_HEIGHT = 450
MAX_UPCOMING_ITEMS = 6
RISK_SOON_DAYS = 2
RISK_WEEK_DAYS = 7


# ========= Helpers =========
def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _prev_month_key() -> str:
    first = date.today().replace(day=1)
    prev_last = first - timedelta(days=1)
    return prev_last.strftime("%Y-%m")


def _days_left(iso: str) -> int:
    try:
        return (date.fromisoformat(iso) - date.today()).days
    except Exception:
        return 9999  # if bad data, treat as far away


def _get_inventory(user_id: int):
    conn = db.get_connection()
    c = conn.cursor()
    c.execute(
        """
        SELECT
          id,
          name,
          expiration,
          COALESCE(type,'Other') as type,
          COALESCE(storage_state,'fresh') as storage_state,
          COALESCE(base_amount, amount, 0) as qty,
          COALESCE(base_unit, unit, 'pcs') as unit,
          COALESCE(price_per_base, 0.0) as ppb,
          COALESCE(money_lost, 0.0) as money_lost
        FROM inventory
        WHERE user_id = ?
        ORDER BY date(expiration) ASC, name ASC
        """,
        (user_id,),
    )
    rows = c.fetchall()
    conn.close()
    # rows: (id, name, expiration, type, state, qty, unit, ppb, money_lost)
    return rows


def _risk_buckets(rows):
    today_ = date.today()
    overdue = 0
    soon = 0
    week = 0
    later = 0
    frozen = 0

    for _, _, exp, _, state, *_ in rows:
        if (state or "fresh") == "frozen":
            frozen += 1
            continue
        try:
            dd = (date.fromisoformat(exp) - today_).days if exp else 9999
        except Exception:
            dd = 9999
        if dd < 0:
            overdue += 1
        elif dd <= RISK_SOON_DAYS:
            soon += 1
        elif dd <= RISK_WEEK_DAYS:
            week += 1
        else:
            later += 1
    return overdue, soon, week, later, frozen


def _top_categories(rows, top_n=3):
    counts = {}
    for _, _, _, typ, _, *_ in rows:
        counts[typ] = counts.get(typ, 0) + 1
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    total = sum(counts.values()) or 1
    return [(k, v, v / total) for k, v in ranked[:top_n]]


def _ai_tips(user_name: str, urgent_names_dates):
    if not _AI_OK:
        return {
            "waste_tip": "Scan fridge weekly; rotate older items forward.",
            "storage_tip": "Keep herbs in jars with a little water.",
            "meal_idea": "Make a quick fried rice with leftovers.",
        }
    item_list = ", ".join([f"{n} ({d})" for n, d in urgent_names_dates]) or "no urgent items"
    prompt = (
        f"You are a concise kitchen coach for {user_name}. "
        f"Urgent items: {item_list}. "
        "Give one 12-20 word tip each: 1) waste reduction, 2) storage, 3) meal idea using at least one urgent item. "
        "Return three lines only."
    )
    try:
        # Backward compatible call; will fail gracefully if not configured
        res = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": prompt}],
            max_tokens=120,
        )
        text = res.choices[0].message["content"].strip()
        parts = [p.strip("-• ").strip() for p in text.splitlines() if p.strip()]
        return {
            "waste_tip": parts[0] if len(parts) > 0 else "Track expiry dates weekly.",
            "storage_tip": parts[1] if len(parts) > 1 else "Use airtight containers for leftovers.",
            "meal_idea": parts[2] if len(parts) > 2 else "Pasta toss with nearing veggies.",
        }
    except Exception:
        return {
            "waste_tip": "Track expiry dates weekly.",
            "storage_tip": "Use airtight containers for leftovers.",
            "meal_idea": "Pasta toss with nearing veggies.",
        }


# ========= MAIN VIEW =========
def calendar_view():
    if "user_id" not in st.session_state:
        st.warning("Please log in first.")
        return

    user_id = st.session_state["user_id"]
    user_name = st.session_state.get("name", "User")

    # Data
    rows = _get_inventory(user_id)
    total_items = len(rows)

    # KPI summaries (this month and delta vs last month)
    now_key = _month_key(date.today())
    prev_key = _prev_month_key()
    cur = db.get_monthly_summary(user_id, month_key=now_key)
    prev = db.get_monthly_summary(user_id, month_key=prev_key)

    used_delta = cur["used_steps"] - prev["used_steps"]
    exp_delta = cur["expired_steps"] - prev["expired_steps"]
    money_delta = round(cur["money_lost"] - prev["money_lost"], 2)

    overdue, soon, week, later, frozen = _risk_buckets(rows)

    # Upcoming list (info-only)
    today_ = date.today()
    upcoming = []
    for _id, name, exp, typ, state, *_ in rows:
        if not exp:
            continue
        d = date.fromisoformat(exp)
        if state != "frozen" and d <= today_ + timedelta(days=RISK_WEEK_DAYS):
            upcoming.append((name, exp, typ, state, _days_left(exp)))
    upcoming = sorted(upcoming, key=lambda t: t[4])[:MAX_UPCOMING_ITEMS]

    # AI tips
    ai_tips = _ai_tips(user_name, [(n, e) for n, e, *_ in upcoming])

    # ======= Layout =======
    st.markdown(f"## 👋 Welcome back, {user_name}")
    st.caption("A quick snapshot of your kitchen. No clicks, just clarity.")

    # Tips row
    c1, c2, c3 = st.columns(3)
    c1.info(f"💡 Waste tip: {ai_tips['waste_tip']}")
    c2.success(f"📦 Storage tip: {ai_tips['storage_tip']}")
    c3.warning(f"🍽 Meal idea: {ai_tips['meal_idea']}")

    # KPI cards (with deltas vs last month)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("📦 Items", total_items)
    k2.metric("✅ Used (mo)", cur["used_steps"], delta=f"{used_delta:+}")
    k3.metric("⛔ Expired (mo)", cur["expired_steps"], delta=f"{exp_delta:+}")
    k4.metric("💰 Money lost (mo)", f"₪{cur['money_lost']:.2f}", delta=f"{money_delta:+.2f}")

    # Risk overview
    st.markdown("### 🧭 Freshness overview")
    r1, r2, r3, r4, r5 = st.columns(5)
    r1.error(f"Overdue: {overdue}")
    r2.warning(f"0–{RISK_SOON_DAYS} days: {soon}")
    r3.info(f"{RISK_SOON_DAYS+1}–{RISK_WEEK_DAYS} days: {week}")
    r4.write(f"Later: {later}")
    r5.write(f"❄️ Frozen: {frozen}")

    # Top categories
    st.markdown("### 🏷 Top categories")
    topcats = _top_categories(rows)
    if topcats:
        for name, count, ratio in topcats:
            st.progress(min(max(ratio, 0.0), 1.0), text=f"{name}: {count}")
    else:
        st.caption("No categories yet.")

    # Upcoming (info only)
    st.markdown("### ⏳ Expiring within 7 days")
    if upcoming:
        for name, exp, typ, state, left in upcoming:
            icon = "❄️ " if state == "frozen" else ("⚠️ " if left <= RISK_SOON_DAYS else "⏳ ")
            cols = st.columns([3, 2, 2, 1])
            cols[0].markdown(f"**{name}**  ·  _{typ}_")
            cols[1].markdown(f"📅 {exp}")
            cols[2].markdown("Frozen" if state == "frozen" else f"{left} day(s) left")
            cols[3].markdown(" ")  # spacer to keep layout tidy
    else:
        st.info("Nothing urgent this week. Nicely done.")

    # Compact calendar
    st.markdown("### 📅 Your week at a glance")
    events = []
    for _id, name, exp, typ, state, *_ in rows:
        if not exp:
            continue
        color = "#33BFFF" if state == "frozen" else ("#ff6b6b" if _days_left(exp) <= RISK_SOON_DAYS else "#1dd1a1")
        events.append({
            "title": f"{name} ({typ})" + (" • Frozen" if state == "frozen" else ""),
            "start": exp,
            "end": exp,
            "color": color,
        })

    calendar(
        events=events,
        options={
            "initialView": "listWeek",
            "height": CALENDAR_HEIGHT,
            "headerToolbar": {"left": "", "center": "title", "right": ""},
        },
    )

    # Gentle footer
    st.caption("Stats reset monthly. Money lost and step counts come from your usage log.")


# For Streamlit multi-page setups:
def app():
    calendar_view()
