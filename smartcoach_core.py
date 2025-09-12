# smartcoach_core.py
# SmartCoach core: waste-minimization advisor.
# Provides: critical warnings (today/expired), urgent risks (next 1–3 days),
# recipe rescue recommendations, preventive moves (4–7 days), quick tips,
# and now: Dismiss = Snooze (persisted hide).

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

from db import get_connection, create_tables

FAR_FUTURE = "9999-12-31"

# Types that are commonly freezable or benefit from freezing
FREEZABLE_TYPES = {"Meat", "Seafood", "Dairy", "Frozen"}
FREEZABLE_NAME_HINTS = {"bread", "pita", "baguette", "tortilla", "wrap", "bananas", "herbs"}
# Types that are typically fast-perishing
FAST_PERISH_TYPES = {"Meat", "Seafood", "Dairy", "Fruit", "Vegetable", "Dessert"}
# Reasonable default freeze extension if the UI doesn't specify
DEFAULT_FREEZE_EXT_DAYS = 30

# ------------------------------
# Migrations (logs + snooze table)
# ------------------------------
SMARTCOACH_MIGRATIONS = [
    ("""
     CREATE TABLE IF NOT EXISTS coach_actions_log (
       id INTEGER PRIMARY KEY AUTOINCREMENT,
       user_id INTEGER NOT NULL,
       item_id INTEGER NOT NULL,
       action TEXT NOT NULL,             -- 'freeze' | 'use' | 'throw' | 'dismiss'
       qty_base REAL,                    -- may be NULL for dismiss
       extra_days INTEGER,               -- for freeze
       note TEXT,
       ts TEXT NOT NULL
     )
    """,),
    ("""
     CREATE TABLE IF NOT EXISTS coach_snooze (
       user_id INTEGER NOT NULL,
       item_id INTEGER NOT NULL,
       until  TEXT NOT NULL,
       PRIMARY KEY (user_id, item_id)
     )
    """,),
]

def run_smartcoach_migrations():
    create_tables()
    conn = get_connection(); c = conn.cursor()
    for (stmt,) in SMARTCOACH_MIGRATIONS:
        try:
            c.execute(stmt); conn.commit()
        except Exception:
            pass
    conn.close()

# ------------------------------
# Helpers
# ------------------------------
def _today_iso() -> str:
    return date.today().strftime("%Y-%m-%d")

def _iso_plus_days(days: int) -> str:
    return (date.today() + timedelta(days=int(days))).strftime("%Y-%m-%d")

def _days_until(iso: Optional[str]) -> Optional[int]:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(iso).date()
        return (d - date.today()).days
    except Exception:
        return None

def _value_shekel(base_amount: float, ppb: float) -> float:
    amt = float(base_amount or 0.0); price = float(ppb or 0.0)
    return round(amt * price, 2)

# ------------------------------
# Inventory access
# ------------------------------
def get_inventory_rows(user_id: int) -> List[Tuple]:
    """
    Return rows:
      id, name, type, base_unit, base_amount, price_per_base, expiration
    """
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, name, type, base_unit, COALESCE(base_amount,0.0), COALESCE(price_per_base,0.0), expiration
        FROM inventory
       WHERE user_id=? AND COALESCE(stable,1)=1
       ORDER BY name
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

# ------------------------------
# Snooze (Dismiss) support
# ------------------------------
def _snoozed_ids(user_id: int) -> set[int]:
    """Return item_ids snoozed through today (inclusive)."""
    conn = get_connection(); c = conn.cursor()
    try:
        c.execute("""
          SELECT item_id FROM coach_snooze
           WHERE user_id=? AND until >= ?
        """, (user_id, _today_iso()))
        return {int(r[0]) for r in c.fetchall()}
    finally:
        conn.close()

def snooze_item(user_id: int, item_id: int, days: int = 3) -> None:
    """Hide an item from coach lists for N days."""
    until = _iso_plus_days(days)
    conn = get_connection(); c = conn.cursor()
    try:
        c.execute("""
          INSERT INTO coach_snooze(user_id, item_id, until)
          VALUES (?,?,?)
          ON CONFLICT(user_id, item_id) DO UPDATE SET until=excluded.until
        """, (user_id, int(item_id), until))
        c.execute("""
          INSERT INTO coach_actions_log(user_id, item_id, action, qty_base, extra_days, note, ts)
          VALUES (?,?,?,?,?,?,?)
        """, (user_id, item_id, "dismiss", None, None, f"snoozed {days}d", _today_iso()))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def clear_snooze(user_id: int, item_id: int) -> None:
    conn = get_connection(); c = conn.cursor()
    try:
        c.execute("DELETE FROM coach_snooze WHERE user_id=? AND item_id=?", (user_id, int(item_id)))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()

# ------------------------------
# Critical warnings (expiry today / already expired)
# ------------------------------
def get_critical_warnings(user_id: int) -> Dict[str, List[Dict[str, Any]]]:
    """
    Returns:
      {
        "expired": [ {item_id, name, type, base_unit, on_hand, value, days}, ... ],
        "today":   [ { ... days: 0 }, ... ]
      }
    """
    out = {"expired": [], "today": []}
    for iid, nm, typ, bu, amt, ppb, exp in get_inventory_rows(user_id):
        if not exp or exp == FAR_FUTURE:
            continue
        d = _days_until(exp)
        if d is None:
            continue
        row = {
            "item_id": iid, "name": nm, "type": typ, "base_unit": bu,
            "on_hand": float(amt), "unit_value": float(ppb),
            "value": _value_shekel(amt, ppb), "expiry": exp, "days": d
        }
        if d < 0 and amt > 0:
            out["expired"].append(row)
        elif d == 0 and amt > 0:
            out["today"].append(row)
    # Sort: biggest value first
    out["expired"].sort(key=lambda r: (-r["value"], r["days"]))
    out["today"].sort(key=lambda r: (-r["value"], r["name"]))
    return out

# ------------------------------
# Urgent risks (next N days)
# ------------------------------
def _risk_score(days_left: int, value: float, typ: str) -> float:
    urgency = max(0.0, 4 - max(days_left, 0)) / 4.0    # 0..1 over the next ~4 days
    money = min(1.0, value / 50.0)                      # saturate around ₪50
    type_boost = 0.15 if typ in FAST_PERISH_TYPES else 0.0
    return urgency * 0.6 + money * 0.4 + type_boost

def _suggest_action_for_urgent(name: str, typ: str, days: int, amt: float, bu: str) -> Tuple[str, str]:
    nm = (name or "").lower()
    if typ in {"Meat", "Seafood"} and days <= 2:
        return ("freeze", f"{amt:g} {bu} likely won’t be used in {days}d; freezing prevents loss")
    if "milk" in nm and days <= 1:
        return ("cook", "use in pancakes, pudding, béchamel, or freeze as cubes")
    if typ in {"Vegetable", "Fruit"} and days <= 2:
        return ("cook", "use in stir-fry/soup/sauce or roast to extend life")
    if "bread" in nm or "pita" in nm or "baguette" in nm or "tortilla" in nm:
        return ("freeze", "slice/freezer today; toast from frozen")
    if typ == "Dairy" and days <= 2:
        return ("cook", "bake or cook into sauces to extend life")
    return ("use", f"consume within {days} day(s)")

def get_urgent_risks(user_id: int, window_days: int = 3, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Items expiring within window_days. Sorted by risk score.
    Returns: [{item_id, name, type, base_unit, on_hand, expiry, days, value, action, reason}]
    """
    picks: List[Dict[str, Any]] = []
    snoozed = _snoozed_ids(user_id)
    for iid, nm, typ, bu, amt, ppb, exp in get_inventory_rows(user_id):
        if iid in snoozed:
            continue
        if amt <= 0 or not exp or exp == FAR_FUTURE:
            continue
        d = _days_until(exp)
        if d is None or d < 0:
            continue
        if d <= window_days:
            value = _value_shekel(amt, ppb)
            score = _risk_score(d, value, typ)
            action, reason = _suggest_action_for_urgent(nm, typ, d, amt, bu)
            picks.append({
                "item_id": iid, "name": nm, "type": typ, "base_unit": bu,
                "on_hand": float(amt), "unit_value": float(ppb),
                "value": value, "expiry": exp, "days": d,
                "score": round(score, 4), "action": action, "reason": reason
            })
    picks.sort(key=lambda r: (-r["score"], r["days"], -r["value"]))
    return picks[:limit]

# ------------------------------
# Preventive moves (4–7 days out)
# ------------------------------
def _preventive_plan(name: str, typ: str, amt: float, bu: str) -> Optional[Dict[str, Any]]:
    nm = (name or "").lower()
    can_freeze = (typ in FREEZABLE_TYPES) or any(h in nm for h in FREEZABLE_NAME_HINTS)
    if can_freeze and amt >= 2:
        freeze_qty = round(max(1.0, amt * 0.5), 2)
        return {
            "suggestion": "freeze",
            "plan": f"Freeze about {freeze_qty:g} {bu} now to extend shelf life",
            "freeze_qty_base": freeze_qty,
            "freeze_extra_days": DEFAULT_FREEZE_EXT_DAYS
        }
    # non-freezable or low amount → plan usage
    use_qty = round(max(1.0 if bu == "pcs" else 200.0 if bu in ("g", "ml") else 1.0, min(amt, amt*0.5)), 2)
    return {
        "suggestion": "use",
        "plan": f"Schedule a recipe that uses ~{use_qty:g} {bu}",
        "use_qty_base": use_qty
    }

def get_preventive_moves(user_id: int, start_days: int = 4, end_days: int = 7, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Items that are not urgent yet but should be planned (freeze a portion or schedule use).
    Returns: [{item_id, name, type, base_unit, on_hand, expiry, days, suggestion, plan}]
    """
    out: List[Dict[str, Any]] = []
    snoozed = _snoozed_ids(user_id)
    for iid, nm, typ, bu, amt, ppb, exp in get_inventory_rows(user_id):
        if iid in snoozed:
            continue
        if amt <= 0 or not exp or exp == FAR_FUTURE:
            continue
        d = _days_until(exp)
        if d is None or d < start_days or d > end_days:
            continue
        plan = _preventive_plan(nm, typ, amt, bu)
        if plan:
            out.append({
                "item_id": iid, "name": nm, "type": typ, "base_unit": bu,
                "on_hand": float(amt), "unit_value": float(ppb),
                "value": _value_shekel(amt, ppb), "expiry": exp, "days": d,
                **plan
            })
    out.sort(key=lambda r: (-r["value"], r["days"]))
    return out[:limit]

# ------------------------------
# Recipe Rescue
# ------------------------------
def _normalize_ing(name: str) -> str:
    return (name or "").lower().strip().replace("-", " ").replace("_", " ")

def _estimate_missing_count(user_id: int, normalized_ings: List[str]) -> int:
    inv = get_inventory_rows(user_id)
    inv_keys = { _normalize_ing(nm) for _, nm, *_ in inv }
    missing = 0
    for ing in normalized_ings:
        if not ing or len(ing) < 3:
            continue
        if ing in inv_keys:
            continue
        missing += 1
    return missing

def get_rescue_recipes(user_id: int, max_recipes: int = 6, lookahead_days: int = 3) -> List[Dict[str, Any]]:
    risky = get_urgent_risks(user_id, window_days=lookahead_days, limit=50)
    if not risky:
        return []

    risky_names = [r["name"].lower() for r in risky]
    risky_keys = set(_normalize_ing(n) for n in risky_names)

    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('recipes','recipe_ingredients')")
    existing = {row[0] for row in c.fetchall()}
    if not {"recipes", "recipe_ingredients"}.issubset(existing):
        conn.close()
        return []

    c.execute("""
      SELECT r.id, r.title, COALESCE(r.url, '')
        FROM recipes r
       WHERE r.user_id=? OR r.user_id IS NULL
       ORDER BY r.id DESC
       LIMIT 500
    """, (user_id,))
    recipes = c.fetchall()

    ids = [rid for rid, _, _ in recipes]
    if not ids:
        conn.close(); return []
    qmarks = ",".join("?" for _ in ids)
    c.execute(f"""
      SELECT recipe_id, ingredient_name
        FROM recipe_ingredients
       WHERE recipe_id IN ({qmarks})
    """, ids)
    ing_map: Dict[int, List[str]] = {}
    for rid, ing in c.fetchall():
        ing_map.setdefault(rid, []).append(ing or "")

    conn.close()

    suggestions: List[Dict[str, Any]] = []
    for rid, title, url in recipes:
        ings = [(_normalize_ing(x)) for x in ing_map.get(rid, [])]
        hits = sorted({orig for orig in risky_names if _normalize_ing(orig) in ings})
        if not hits:
            continue
        missing = _estimate_missing_count(user_id, ings)
        suggestions.append({
            "recipe_id": rid, "title": title, "url": url or None,
            "hit_items": hits, "missing_count": missing
        })

    suggestions.sort(key=lambda r: (-len(r["hit_items"]), r["missing_count"], r["title"].lower()))
    return suggestions[:max_recipes]

# ------------------------------
# Actions: freeze / use / throw
# ------------------------------
def apply_freeze(user_id: int, item_id: int, qty_base: float, extra_days: int = DEFAULT_FREEZE_EXT_DAYS) -> Tuple[bool, str]:
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT base_amount, expiration, frozen_days_accum, storage_state FROM inventory WHERE id=?", (item_id,))
    row = c.fetchone()
    if not row:
        conn.close(); return False, "Item not found."
    base_amount, exp, _frozen_days, _storage_state = row
    if float(base_amount or 0.0) <= 0:
        conn.close(); return False, "No quantity on hand to freeze."

    if exp and exp != FAR_FUTURE:
        try:
            cur = datetime.fromisoformat(exp).date()
        except Exception:
            cur = date.today()
    else:
        cur = date.today()
    new_exp = (cur + timedelta(days=int(extra_days))).strftime("%Y-%m-%d")

    try:
        c.execute("""
          UPDATE inventory
             SET expiration=?,
                 frozen_days_accum=COALESCE(frozen_days_accum,0)+?,
                 storage_state='frozen'
           WHERE id=?
        """, (new_exp, int(extra_days), item_id))
        c.execute("""
          INSERT INTO coach_actions_log(user_id, item_id, action, qty_base, extra_days, note, ts)
          VALUES (?,?,?,?,?,?,?)
        """, (user_id, item_id, "freeze", float(qty_base or 0.0), int(extra_days), "coach-freeze", _today_iso()))
        conn.commit()
        return True, f"Frozen. New expiry {new_exp} (+{int(extra_days)}d)."
    except Exception as e:
        conn.rollback()
        return False, f"Freeze failed: {e}"
    finally:
        conn.close()

def _consume_base_amount(c: Any, item_id: int, delta_base: float):
    c.execute("SELECT COALESCE(base_amount,0.0) FROM inventory WHERE id=?", (item_id,))
    on = float(c.fetchone()[0] or 0.0)
    new_amt = max(0.0, on + float(delta_base))
    c.execute("UPDATE inventory SET base_amount=? WHERE id=?", (new_amt, item_id))
    return on, new_amt

def mark_used_now(user_id: int, item_id: int, qty_base: float) -> Tuple[bool, str]:
    conn = get_connection(); c = conn.cursor()
    try:
        before, after = _consume_base_amount(c, item_id, -abs(qty_base))
        c.execute("SELECT base_unit FROM inventory WHERE id=?", (item_id,))
        bu = (c.fetchone() or ["pcs"])[0] or "pcs"
        step = 100.0 if bu in ("g", "ml") else 1.0
        steps = max(1, int(round(abs(qty_base) / step)))
        c.execute("""
          INSERT INTO usage_log(user_id, item_id, event_type, step_count, ts)
          VALUES (?,?,?,?,?)
        """, (user_id, item_id, "used", steps, _today_iso()))
        c.execute("""
          INSERT INTO coach_actions_log(user_id, item_id, action, qty_base, extra_days, note, ts)
          VALUES (?,?,?,?,?,?,?)
        """, (user_id, item_id, "use", float(qty_base), None, "coach-use", _today_iso()))
        conn.commit()
        return True, f"Used {qty_base:g} (base). Remaining {after:g}."
    except Exception as e:
        conn.rollback()
        return False, f"Use failed: {e}"
    finally:
        conn.close()

def mark_thrown_now(user_id: int, item_id: int, qty_base: float) -> Tuple[bool, str]:
    conn = get_connection(); c = conn.cursor()
    try:
        before, after = _consume_base_amount(c, item_id, -abs(qty_base))
        steps = max(1, int(round(abs(qty_base))))
        c.execute("UPDATE inventory SET expired_count=COALESCE(expired_count,0)+? WHERE id=?", (steps, item_id))
        c.execute("""
          INSERT INTO usage_log(user_id, item_id, event_type, step_count, ts)
          VALUES (?,?,?,?,?)
        """, (user_id, item_id, "expired", steps, _today_iso()))
        c.execute("""
          INSERT INTO coach_actions_log(user_id, item_id, action, qty_base, extra_days, note, ts)
          VALUES (?,?,?,?,?,?,?)
        """, (user_id, item_id, "throw", float(qty_base), None, "coach-throw", _today_iso()))
        conn.commit()
        return True, f"Discarded {qty_base:g}. Remaining {after:g}."
    except Exception as e:
        conn.rollback()
        return False, f"Discard failed: {e}"
    finally:
        conn.close()

def dismiss_item(user_id: int, item_id: int, note: str = "") -> None:
    # kept for compatibility; prefer snooze_item()
    snooze_item(user_id, item_id, days=3)

# ------------------------------
# Quick tips (micro-habits)
# ------------------------------
def _has_item_like(user_id: int, needles: List[str]) -> bool:
    inv = get_inventory_rows(user_id)
    names = " ".join((nm or "").lower() for _, nm, *_ in inv)
    return any(n in names for n in needles)

def _most_frequently_expired(user_id: int) -> Optional[Tuple[str, int]]:
    conn = get_connection(); c = conn.cursor()
    try:
        since = (date.today() - timedelta(days=60)).strftime("%Y-%m-%d")
        c.execute("""
          SELECT i.name, SUM(COALESCE(u.step_count,0)) as s
            FROM usage_log u
            JOIN inventory i ON i.id = u.item_id
           WHERE u.user_id=? AND u.event_type='expired' AND substr(u.ts,1,10)>=?
           GROUP BY i.name
           ORDER BY s DESC
           LIMIT 1
        """, (user_id, since))
        row = c.fetchone()
        if row and int(row[1] or 0) > 0:
            return (row[0], int(row[1]))
        return None
    except Exception:
        return None
    finally:
        c.connection.close()

def quick_tips(user_id: int, limit: int = 3) -> List[str]:
    tips: List[str] = []
    frequent = _most_frequently_expired(user_id)
    if frequent:
        item, count = frequent
        tips.append(f"“{item}” expired {count} times recently. Buy smaller packs or plan a recipe when you add it.")
    if _has_item_like(user_id, ["milk", "yogurt", "labneh"]):
        tips.append("Freeze milk or yogurt in ice-cube trays for sauces and smoothies when they near expiry.")
    if _has_item_like(user_id, ["bread", "pita", "baguette", "tortilla"]):
        tips.append("Slice bread and freeze half on day 1; toast straight from frozen to avoid staling.")
    if _has_item_like(user_id, ["parsley", "coriander", "cilantro", "lettuce", "spinach"]):
        tips.append("Wrap herbs in paper towel inside a vented container; replace towel every 2 days.")
    return tips[:limit]

# ------------------------------
# High-level snapshot
# ------------------------------
def coach_snapshot(user_id: int) -> Dict[str, Any]:
    run_smartcoach_migrations()
    critical = get_critical_warnings(user_id)
    urgent = get_urgent_risks(user_id, window_days=3, limit=5)
    preventive = get_preventive_moves(user_id, start_days=4, end_days=7, limit=10)
    recipes = get_rescue_recipes(user_id, max_recipes=6, lookahead_days=3)
    tips = quick_tips(user_id, limit=3)
    return {
        "critical": critical,
        "urgent": urgent,
        "preventive": preventive,
        "recipes": recipes,
        "tips": tips
    }
