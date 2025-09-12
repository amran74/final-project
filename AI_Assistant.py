# AI_Assistant.py
# UI for the "AI Command Center" page.
# Natural-language actions with dry-run preview, then Apply.
# Uses ai_commands_core.py as the execution brain.

from __future__ import annotations

import sys as _sys
from typing import Any, Dict

import streamlit as st
import ai_commands_core as aic

# Router compatibility: keep module name stable for dynamic loaders
_mod = _sys.modules.get(__name__)
if _mod is not None:
    _sys.modules.setdefault("AI_Assistant", _mod)
    _sys.modules.setdefault("ai_assistant", _mod)

# -----------------------------
# Helpers
# -----------------------------
def _ensure_state():
    st.session_state.setdefault("ai_history", [])   # list of {"text": str, "plan": dict, "result": dict}
    st.session_state.setdefault("ai_input_seed", "")  # seed value for the text_input (avoid modifying widget state)

def _render_plan(plan: Dict[str, Any]):
    st.markdown(f"**Summary:** {plan.get('summary','')}")
    inv = plan.get("inventory_deltas") or []
    cart = plan.get("cart_adds") or []
    notes = plan.get("notes") or []

    if isinstance(inv, list) and inv and isinstance(inv[0], dict) and "op" in inv[0]:
        st.subheader("Inventory changes (dry-run)")
        for row in inv:
            name = row.get("name", "item")
            op = row.get("op")
            if op == "freeze":
                old = row.get("expiry_old")
                new = row.get("expiry_new")
                st.write(f"• **{name}** → freeze {row.get('qty')} {row.get('unit')}  | expiry {old} → **{new}**")
            elif op == "use":
                st.write(f"• **{name}** → use {row.get('qty')} {row.get('unit')}")
            elif op == "throw":
                st.write(f"• **{name}** → discard {row.get('qty')} {row.get('unit')}")
    elif isinstance(inv, list) and inv:
        first = inv[0]
        if "days" in first and "name" in first:
            st.subheader("Items")
            for r in inv:
                days = r.get("days")
                days_txt = "today" if days == 0 else (f"in {days}d" if days and days > 0 else "expired")
                st.write(f"• **{r.get('name')}**  · {r.get('type','')}  · on hand {r.get('on_hand','?')} {r.get('base_unit','')}  · {days_txt}")
        elif "recipe_id" in first or "title" in first:
            st.subheader("Recipes")
            for r in inv:
                title = r.get("title") or "Recipe"
                hits = ", ".join(r.get("hit_items", []) or [])
                miss = r.get("missing_count", 0)
                if r.get("url"):
                    st.markdown(f"• **[{title}]({r['url']})** — uses: {hits} · missing: {miss}")
                else:
                    st.write(f"• **{title}** — uses: {hits} · missing: {miss}")

    if cart:
        st.subheader("Cart additions (dry-run)")
        for c in cart:
            st.write(f"• {c.get('store')}: add {c.get('qty')} {c.get('unit','pcs')} {c.get('name')}")

    if notes:
        with st.expander("Notes"):
            for n in notes:
                st.json(n)

def _examples_row():
    examples = [
        "freeze 300 g chicken breast +30d",
        "use 2 eggs",
        "throw 1 yogurt",
        "add 2x milk to Osher Ad",
        "show expiring weekend",
        "what is at risk next 7 days",
        "plan recipe using spinach, feta",
    ]
    cols = st.columns(len(examples))
    for i, ex in enumerate(examples):
        if cols[i].button(ex, key=f"ai_ex_{i}"):
            # Don't touch the text_input's state directly. Seed and rerun.
            st.session_state["ai_input_seed"] = ex
            st.rerun()

def _commit_and_log(text: str, plan: Dict[str, Any], result: Dict[str, Any]):
    st.session_state["ai_history"].insert(0, {"text": text, "plan": plan, "result": result})
    st.success(result.get("message", "Done."))
    st.rerun()

# -----------------------------
# Main UI
# -----------------------------
def ai_page():
    st.title("🤖 AI Command Center")

    if "user_id" not in st.session_state:
        st.warning("Please login first.")
        st.stop()
    user_id = int(st.session_state["user_id"])

    _ensure_state()

    # Examples FIRST so any click seeds input before widget is built
    _examples_row()
    st.caption("Type a command, then Preview → Apply.")

    # Input area
    with st.form("ai_cmd_form", clear_on_submit=False):
        text = st.text_input(
            "Command",
            key="ai_input",
            value=st.session_state.get("ai_input_seed", ""),
            placeholder="e.g., freeze 300 g chicken breast +30d",
        )
        c1, c2, c3 = st.columns([1, 1, 6])
        do_preview = c1.form_submit_button("Preview")
        clear_btn = c2.form_submit_button("Clear")

    if clear_btn:
        st.session_state["ai_input_seed"] = ""
        st.rerun()

    st.divider()

    # Preview handling
    if do_preview and (text or "").strip():
        try:
            cmd = aic.parse(text, user_id)
            plan = aic.dry_run(cmd, user_id)
            st.subheader("Preview")
            _render_plan(plan)
            c1, c2 = st.columns([1, 5])
            if c1.button("Apply", key="ai_apply"):
                result = aic.apply(cmd, user_id)
                _commit_and_log(text, plan, result)
            if c2.button("Cancel", key="ai_cancel"):
                st.info("Cancelled.")
        except Exception as e:
            st.error(f"{e}")

    # History
    if st.session_state["ai_history"]:
        st.divider()
        st.subheader("Recent commands")
        for i, entry in enumerate(st.session_state["ai_history"]):
            with st.expander(f"{entry.get('text','(no text)')}"):
                st.markdown("**Preview**")
                _render_plan(entry.get("plan", {}))
                st.markdown("**Result**")
                st.write(entry.get("result", {}))
        if st.button("Clear history"):
            st.session_state["ai_history"].clear()
            st.rerun()

    st.divider()

    # Automations
    with st.expander("⚙️ Automations"):
        st.caption("Simple rules: `if <item> < <qty><unit> then add <n> to <store>`")
        try:
            logs = aic.run_automations(user_id)
            if logs:
                st.write("Evaluated on open:")
                for lg in logs:
                    st.write(f"• {lg}")
        except Exception:
            pass

        st.markdown("---")
        st.markdown("**Your rules**")
        try:
            rules = aic.list_rules(user_id)
            if not rules:
                st.write("No rules yet.")
            else:
                for rid, rule, enabled in rules:
                    c1, c2, c3, c4 = st.columns([6, 1, 1, 1])
                    c1.write(rule)
                    if c2.button("On" if not enabled else "Off", key=f"rule_toggle_{rid}"):
                        aic.set_rule_enabled(user_id, rid, not bool(enabled))
                        st.rerun()
                    if c3.button("Run", key=f"rule_run_{rid}"):
                        notes = aic.run_automations(user_id)
                        if notes:
                            st.toast("\n".join(notes))
                        else:
                            st.toast("No actions executed.")
                    if c4.button("Delete", key=f"rule_del_{rid}"):
                        aic.delete_rule(user_id, rid)
                        st.rerun()
        except Exception as e:
            st.error(f"Rules error: {e}")

        st.markdown("---")
        st.markdown("**Add rule**")
        with st.form("add_rule_form", clear_on_submit=True):
            rule_text = st.text_input("Rule", placeholder="if milk < 300 ml then add 1 to Osher Ad")
            add_ok = st.form_submit_button("Add")
        if add_ok and rule_text.strip():
            try:
                aic.add_rule(user_id, rule_text.strip())
                st.success("Rule added.")
                st.rerun()
            except Exception as e:
                st.error(f"{e}")

# Entry points for router
def ai_assistant():
    ai_page()

def app():
    ai_page()

# Some routers expect a symbol equal to the module name
AI_Assistant = ai_assistant

if __name__ == "__main__":
    ai_page()
