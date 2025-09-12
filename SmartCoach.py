# SmartCoach.py
# Streamlit UI for SmartCoach (advisor mode).
# Renders: Critical warnings (today/expired), Urgent risks (next 1–3 days),
# Recipe Rescue, Preventive moves (4–7 days), Quick tips.
#
# All logic lives in smartcoach_core.py.

from __future__ import annotations

from typing import Optional
import sys as _sys
import streamlit as st

import smartcoach_core as core

# Router compatibility: play nice with weird dynamic loaders
_mod = _sys.modules.get(__name__)
if _mod is not None:
    _sys.modules.setdefault("SmartCoach", _mod)
    _sys.modules.setdefault("smartcoach", _mod)


# -----------------------------
# Small helpers
# -----------------------------
def _step_for(base_unit: str) -> float:
    return 100.0 if base_unit in ("g", "ml") else 1.0

def _qty_input(label: str, key: str, default: float, base_unit: str):
    step = _step_for(base_unit)
    return st.number_input(label, min_value=0.0, step=step, value=float(default or 0.0), key=key)

def _action_row_prefix(name: str, typ: str, base_unit: str, on_hand: float,
                       expiry: Optional[str], days: Optional[int]):
    details = f"[{typ} · {base_unit}] · on hand: {on_hand:g}"
    if expiry:
        if days is None:
            when = f"expiry: {expiry}"
        elif days < 0:
            when = f"expired {-days}d ago"
        elif days == 0:
            when = "expires today"
        else:
            when = f"expires in {days}d"
        details += f" · {when}"
    st.markdown(f"**{name}**  \n{details}")

def _success_and_rerun(msg: str):
    st.success(msg)
    st.rerun()


# -----------------------------
# UI
# -----------------------------
def smartcoach():
    st.title("🧠 SmartCoach — Waste Minimizer")

    if "user_id" not in st.session_state:
        st.warning("Please login first")
        st.stop()
    user_id = int(st.session_state["user_id"])

    snap = core.coach_snapshot(user_id)

    # ---------------- Critical warnings ----------------
    critical = snap.get("critical", {})
    expired_rows = critical.get("expired", []) or []
    today_rows = critical.get("today", []) or []

    if expired_rows or today_rows:
        with st.container():
            if today_rows:
                st.error(f"⚠️ {len(today_rows)} item(s) expire **TODAY** — use or discard immediately.")
                for r in today_rows:
                    c1, c2, c3, c4 = st.columns([2.6, 1.2, 1.2, 1.2])
                    with c1:
                        _action_row_prefix(r["name"], r["type"], r["base_unit"], r["on_hand"], r["expiry"], r["days"])
                    use_qty = c2.number_input("Use qty", min_value=0.0, step=_step_for(r["base_unit"]),
                                              value=float(r["on_hand"]), key=f"crt_use_{r['item_id']}")
                    if c3.button("Use now", key=f"crt_use_btn_{r['item_id']}"):
                        ok, msg = core.mark_used_now(user_id, r["item_id"], use_qty)
                        _success_and_rerun(msg if ok else f"Use failed: {msg}")
                    throw_qty = c4.number_input("Throw qty", min_value=0.0, step=_step_for(r["base_unit"]),
                                                value=0.0, key=f"crt_thr_{r['item_id']}")
                    if c4.button("Throw", key=f"crt_thr_btn_{r['item_id']}"):
                        ok, msg = core.mark_thrown_now(user_id, r["item_id"], throw_qty or r["on_hand"])
                        _success_and_rerun(msg if ok else f"Discard failed: {msg}")
                st.divider()

            if expired_rows:
                st.error(f"🧪 {len(expired_rows)} item(s) already **EXPIRED** — discard for safety.")
                for r in expired_rows:
                    c1, c2, c3 = st.columns([2.6, 1.2, 1.2])
                    with c1:
                        _action_row_prefix(r["name"], r["type"], r["base_unit"], r["on_hand"], r["expiry"], r["days"])
                    thr_qty = c2.number_input("Throw qty", min_value=0.0, step=_step_for(r["base_unit"]),
                                              value=float(r["on_hand"]), key=f"exp_thr_{r['item_id']}")
                    if c3.button("Throw now", key=f"exp_thr_btn_{r['item_id']}"):
                        ok, msg = core.mark_thrown_now(user_id, r["item_id"], thr_qty)
                        _success_and_rerun(msg if ok else f"Discard failed: {msg}")
                st.divider()

    # ---------------- Urgent risks ----------------
    urgent = snap.get("urgent", []) or []
    st.subheader("⏱️ Urgent risks (next 1–3 days)")
    if not urgent:
        st.caption("No urgent risks. Breathe.")
    else:
        for r in urgent:
            c1, c2, c3, c4, c5 = st.columns([2.8, 1.1, 1.1, 1.2, 1.2])
            with c1:
                _action_row_prefix(r["name"], r["type"], r["base_unit"], r["on_hand"], r["expiry"], r["days"])
                st.caption(f"Recommendation: **{r['action']}** — {r['reason']}")
            qty = c2.number_input("Qty", min_value=0.0, step=_step_for(r["base_unit"]),
                                  value=float(r["on_hand"]), key=f"urg_qty_{r['item_id']}")
            if r["action"] == "freeze":
                extra = c3.number_input("+days", min_value=1, step=7,
                                        value=int(core.DEFAULT_FREEZE_EXT_DAYS),
                                        key=f"urg_frz_days_{r['item_id']}")
                if c4.button("Freeze", key=f"urg_frz_btn_{r['item_id']}"):
                    ok, msg = core.apply_freeze(user_id, r["item_id"], qty, extra_days=int(extra))
                    _success_and_rerun(msg if ok else f"Freeze failed: {msg}")
                if c5.button("Dismiss", key=f"urg_dismiss_{r['item_id']}"):
                    core.dismiss_item(user_id, r["item_id"], note="urgent-dismiss")
                    _success_and_rerun("Dismissed")
            elif r["action"] == "cook" or r["action"] == "use":
                if c3.button("Use now", key=f"urg_use_btn_{r['item_id']}"):
                    ok, msg = core.mark_used_now(user_id, r["item_id"], qty)
                    _success_and_rerun(msg if ok else f"Use failed: {msg}")
                if c4.button("Freeze", key=f"urg_frz_btn2_{r['item_id']}"):
                    ok, msg = core.apply_freeze(user_id, r["item_id"], qty, extra_days=int(core.DEFAULT_FREEZE_EXT_DAYS))
                    _success_and_rerun(msg if ok else f"Freeze failed: {msg}")
                if c5.button("Dismiss", key=f"urg_dismiss2_{r['item_id']}"):
                    core.dismiss_item(user_id, r["item_id"], note="urgent-dismiss")
                    _success_and_rerun("Dismissed")

    st.divider()

    # ---------------- Recipe rescue ----------------
    recipes = snap.get("recipes", []) or []
    st.subheader("🍳 Recipe rescue (uses at-risk items)")
    if not recipes:
        st.caption("No matching recipes for the urgent items.")
    else:
        for rec in recipes:
            cols = st.columns([3, 2, 1])
            cols[0].markdown(f"**{rec['title']}**")
            hits = ", ".join(rec.get("hit_items", []))
            cols[1].write(f"Uses: {hits}  · Missing: {rec.get('missing_count', 0)}")
            if rec.get("url"):
                cols[2].markdown(f"[Open recipe]({rec['url']})")
            else:
                cols[2].write("")

    st.divider()

    # ---------------- Preventive moves ----------------
    preventive = snap.get("preventive", []) or []
    st.subheader("🧯 Preventive moves (4–7 days)")
    if not preventive:
        st.caption("Nothing to plan right now.")
    else:
        for r in preventive:
            c1, c2, c3 = st.columns([2.8, 1.2, 1.2])
            with c1:
                _action_row_prefix(r["name"], r["type"], r["base_unit"], r["on_hand"], r["expiry"], r["days"])
                st.caption(f"{r['plan']}")
            if r.get("suggestion") == "freeze":
                fqty = float(r.get("freeze_qty_base", 0.0)) or min(r["on_hand"], max(1.0, r["on_hand"] * 0.5))
                fextra = int(r.get("freeze_extra_days", core.DEFAULT_FREEZE_EXT_DAYS))
                qty = c2.number_input("Freeze qty", min_value=0.0, step=_step_for(r["base_unit"]),
                                      value=float(fqty), key=f"prev_frz_qty_{r['item_id']}")
                extra = c3.number_input("+days", min_value=1, step=7,
                                        value=int(fextra), key=f"prev_frz_days_{r['item_id']}")
                if c3.button("Freeze now", key=f"prev_frz_btn_{r['item_id']}"):
                    ok, msg = core.apply_freeze(user_id, r["item_id"], qty, extra_days=int(extra))
                    _success_and_rerun(msg if ok else f"Freeze failed: {msg}")
            else:
                uqty = float(r.get("use_qty_base", 0.0)) or min(r["on_hand"], max(1.0, r["on_hand"] * 0.5))
                qty = c2.number_input("Use qty", min_value=0.0, step=_step_for(r["base_unit"]),
                                      value=float(uqty), key=f"prev_use_qty_{r['item_id']}")
                if c3.button("Use now", key=f"prev_use_btn_{r['item_id']}"):
                    ok, msg = core.mark_used_now(user_id, r["item_id"], qty)
                    _success_and_rerun(msg if ok else f"Use failed: {msg}")

    st.divider()

    # ---------------- Quick tips ----------------
    tips = snap.get("tips", []) or []
    st.subheader("💡 Quick tips")
    if not tips:
        st.caption("No tips right now.")
    else:
        for t in tips:
            st.write(f"• {t}")


# Entry points for the router
def coach():
    smartcoach()

def app():
    smartcoach()

# also expose direct symbol some routers expect
app = coach

if __name__ == "__main__":
    smartcoach()
