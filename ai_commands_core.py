# ai_commands_core.py
# Core logic for the "AI Command Center" page.
# - Rule-first intent parser (works offline)
# - Dry-run preview of actions
# - Apply commits via shopping_core / smartcoach_core / DB
#
# Supported intents (v1):
#   freeze <qty><unit?> <item> [+<days>?]
#   use <qty><unit?> <item>
#   throw <qty><unit?> <item>
#   add <qty>[x|pcs]? <item> to <store>
#   show expiring [today|tomorrow|weekend|next <N> days]
#   what is at risk [next <N> days]
#   plan recipe using <item>[, <item>...]
#
# Notes:
# - Units: g, ml, pcs (defaults by item type guess)
# - Store name matched fuzzily against DB stores
# - Dry-run object describes what will change before "apply"

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from db import get_connection
import smartcoach_core as coach
try:
    import shopping_core as shop
except Exception:
    shop = None  # graceful fallback; UI can warn if shopping_core missing


# -----------------------------
# Utilities
# -----------------------------

_UNIT_ALIASES = {
    "gram": "g", "grams": "g", "g": "g",
    "ml": "ml", "milliliter": "ml", "milliliters": "ml",
    "piece": "pcs", "pieces": "pcs", "pc": "pcs", "pcs": "pcs", "x": "pcs",
    "unit": "pcs", "units": "pcs",
    "kg": "g", "l": "ml", "liter": "ml", "liters": "ml"
}

def _norm_unit(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    u = u.strip().lower()
    return _UNIT_ALIASES.get(u, u)

def _default_unit_for(name: str, typ: str) -> str:
    nm = (name or "").lower()
    if typ in ("Meat", "Seafood", "Dairy") or any(k in nm for k in ("milk", "yogurt", "cream")):
        return "ml" if any(k in nm for k in ("milk", "cream")) else "g"
    if typ in ("Vegetable", "Fruit", "Grain"):
        return "g"
    return "pcs"

def _today() -> date:
    return date.today()

def _up_to_weekend_days() -> int:
    # days until Saturday (or Sunday if your locale prefers); assume weekend starts in 2 days worst-case
    wd = _today().weekday()  # Mon 0 ... Sun 6
    # assume Fri/Sat weekend → pick 5,6 as weekend; adjust easily
    # We'll consider "this weekend" as within next 3 days if near end of week, else 6.
    return 3 if wd >= 3 else 6

# -----------------------------
# Inventory access (schema-agnostic)
# -----------------------------

@dataclass
class InvRow:
    id: int
    name: str
    typ: str
    base_unit: str
    base_amount: float
    price_per_base: float
    expiration: Optional[str]

def _fetch_inventory(user_id: int) -> List[InvRow]:
    """
    Try to be tolerant to both older and newer schemas.
    """
    conn = get_connection()
    c = conn.cursor()
    rows: List[InvRow] = []

    # Try new-ish schema first (base_* cols)
    try:
        c.execute("""
          SELECT id,
                 COALESCE(name,''),
                 COALESCE(type,'Other'),
                 COALESCE(base_unit, COALESCE(unit,'pcs')),
                 COALESCE(base_amount, COALESCE(amount,0.0)),
                 COALESCE(price_per_base, COALESCE(price_per_unit,0.0)),
                 COALESCE(expiration,'')
            FROM inventory
           WHERE user_id=?
        """, (user_id,))
        for r in c.fetchall():
            rows.append(InvRow(
                id=int(r[0]),
                name=r[1],
                typ=r[2],
                base_unit=r[3] or "pcs",
                base_amount=float(r[4] or 0.0),
                price_per_base=float(r[5] or 0.0),
                expiration=r[6] or None
            ))
    finally:
        conn.close()
    return rows

def _find_item(user_id: int, query: str) -> Optional[InvRow]:
    q = (query or "").lower().strip()
    if not q:
        return None
    best: Optional[InvRow] = None
    rows = _fetch_inventory(user_id)
    for r in rows:
        nm = r.name.lower()
        if q == nm or q in nm or nm in q:
            if best is None or r.base_amount > (best.base_amount if best else -1):
                best = r
    # second pass: startswith token
    if best is None:
        for r in rows:
            if r.name.lower().startswith(q):
                best = r; break
    return best

def _find_store_name(store_query: str) -> Optional[str]:
    if not store_query:
        return None
    q = store_query.lower().strip()
    conn = get_connection(); c = conn.cursor()
    try:
        # attempt common tables
        candidates: List[str] = []
        for table, col in [("stores", "name"), ("shopping_stores", "name")]:
            try:
                c.execute(f"SELECT {col} FROM {table}")
                candidates.extend([row[0] for row in c.fetchall() if row and row[0]])
            except Exception:
                pass
        for name in candidates:
            low = name.lower()
            if q == low or q in low or low in q:
                return name
    finally:
        conn.close()
    return None

# -----------------------------
# Intent model
# -----------------------------

@dataclass
class Command:
    kind: str                # freeze | use | throw | add_to_cart | query_expiring | query_risk | plan_recipe
    item: Optional[str] = None
    qty: Optional[float] = None
    unit: Optional[str] = None
    extra_days: Optional[int] = None
    store: Optional[str] = None
    days: Optional[int] = None
    using_items: Optional[List[str]] = None

_INT_QTY = r"(?P<q>\d+(?:\.\d+)?)\s*(?P<u>kg|g|l|ml|pcs|x|pieces|piece|units|unit)?"
_INT_ITEM = r"(?P<item>[\w\s\-\(\)\/]+?)"
_INT_STORE = r"(?P<store>[\w\s\-\(\)\/]+?)"

def parse(text: str, user_id: int) -> Command:
    """
    Rule-first parser. Returns a Command or raises ValueError.
    """
    if not text or not text.strip():
        raise ValueError("Empty command.")

    s = text.strip().lower()
    s = re.sub(r"\s+", " ", s)

    # add N item to STORE
    m = re.search(rf"^add\s+{_INT_QTY}\s+{_INT_ITEM}\s+to\s+{_INT_STORE}$", s)
    if m:
        qty = float(m.group("q"))
        unit = _norm_unit(m.group("u") or "pcs")
        item = m.group("item").strip()
        store = _find_store_name(m.group("store"))
        if not store:
            raise ValueError("Unknown store.")
        return Command(kind="add_to_cart", item=item, qty=qty, unit=unit, store=store)

    # freeze Q U item [+days]
    m = re.search(rf"^freeze\s+{_INT_QTY}\s+{_INT_ITEM}(?:\s*\+\s*(?P<d>\d+)\s*d(?:ays)?)?$", s)
    if m:
        qty = float(m.group("q")); unit = _norm_unit(m.group("u"))
        item = m.group("item").strip()
        extra = int(m.group("d") or coach.DEFAULT_FREEZE_EXT_DAYS)
        return Command(kind="freeze", item=item, qty=qty, unit=unit, extra_days=extra)

    # use Q U item
    m = re.search(rf"^use\s+{_INT_QTY}\s+{_INT_ITEM}$", s)
    if m:
        return Command(kind="use", item=m.group("item").strip(),
                       qty=float(m.group("q")), unit=_norm_unit(m.group("u")))

    # throw Q U item
    m = re.search(rf"^throw\s+{_INT_QTY}\s+{_INT_ITEM}$", s)
    if m:
        return Command(kind="throw", item=m.group("item").strip(),
                       qty=float(m.group("q")), unit=_norm_unit(m.group("u")))

    # show expiring ...
    if s.startswith("show expiring") or s.startswith("what expires"):
        # today / tomorrow / weekend / next N days
        if "today" in s:
            return Command(kind="query_expiring", days=0)
        if "tomorrow" in s:
            return Command(kind="query_expiring", days=1)
        if "weekend" in s:
            return Command(kind="query_expiring", days=_up_to_weekend_days())
        m = re.search(r"next\s+(\d+)\s+days", s)
        if m:
            return Command(kind="query_expiring", days=int(m.group(1)))
        return Command(kind="query_expiring", days=3)

    # what is at risk next N days
    if s.startswith("what is at risk") or s.startswith("show risk"):
        m = re.search(r"next\s+(\d+)\s+days", s)
        return Command(kind="query_risk", days=int(m.group(1)) if m else 7)

    # plan recipe using a, b
    m = re.search(r"^plan\s+recipe\s+using\s+(.+)$", s)
    if m:
        items = [x.strip() for x in m.group(1).split(",") if x.strip()]
        return Command(kind="plan_recipe", using_items=items or None)

    raise ValueError("Could not understand the command.")

# -----------------------------
# Dry-run
# -----------------------------

def _coerce_qty_unit(inv: InvRow, qty: Optional[float], unit: Optional[str]) -> Tuple[float, str]:
    u = _norm_unit(unit) or inv.base_unit or _default_unit_for(inv.name, inv.typ)
    q = float(qty or inv.base_amount or 0.0)
    # simple kg/l to base
    if u == "kg":
        q = q * 1000.0; u = "g"
    if u == "l":
        q = q * 1000.0; u = "ml"
    return q, u

def dry_run(cmd: Command, user_id: int) -> Dict[str, Any]:
    """
    Return a plan description without mutating anything.
    """
    plan: Dict[str, Any] = {"summary": "", "inventory_deltas": [], "cart_adds": [], "notes": []}

    if cmd.kind in ("freeze", "use", "throw"):
        inv = _find_item(user_id, cmd.item or "")
        if not inv:
            raise ValueError("Item not found in inventory.")
        qty, unit = _coerce_qty_unit(inv, cmd.qty, cmd.unit)

        if cmd.kind == "freeze":
            new_exp = None
            if inv.expiration:
                try:
                    cur = date.fromisoformat(inv.expiration)
                except Exception:
                    cur = _today()
            else:
                cur = _today()
            new_exp = (cur + timedelta(days=int(cmd.extra_days or coach.DEFAULT_FREEZE_EXT_DAYS))).strftime("%Y-%m-%d")
            plan["summary"] = f"Freeze {qty:g} {unit} of {inv.name} (+{int(cmd.extra_days or coach.DEFAULT_FREEZE_EXT_DAYS)}d)"
            plan["inventory_deltas"].append({
                "item_id": inv.id, "name": inv.name, "op": "freeze",
                "qty": qty, "unit": unit, "expiry_old": inv.expiration, "expiry_new": new_exp
            })
            return plan

        if cmd.kind == "use":
            plan["summary"] = f"Use {qty:g} {unit} of {inv.name}"
            plan["inventory_deltas"].append({"item_id": inv.id, "name": inv.name, "op": "use", "qty": qty, "unit": unit})
            return plan

        if cmd.kind == "throw":
            plan["summary"] = f"Discard {qty:g} {unit} of {inv.name}"
            plan["inventory_deltas"].append({"item_id": inv.id, "name": inv.name, "op": "throw", "qty": qty, "unit": unit})
            return plan

    if cmd.kind == "add_to_cart":
        if not shop:
            raise RuntimeError("Shopping core not available.")
        plan["summary"] = f"Add {cmd.qty:g} {cmd.unit or 'pcs'} of {cmd.item} to {cmd.store}"
        plan["cart_adds"].append({
            "store": cmd.store, "name": cmd.item, "qty": float(cmd.qty or 1.0), "unit": cmd.unit or "pcs"
        })
        return plan

    if cmd.kind == "query_expiring":
        window = int(cmd.days or 3)
        crit = coach.get_critical_warnings(user_id)
        urgent = coach.get_urgent_risks(user_id, window_days=window, limit=50)
        plan["summary"] = f"Show items expiring within {window} day(s)"
        plan["notes"].append({"critical_today": len(crit.get("today", [])), "critical_expired": len(crit.get("expired", []))})
        plan["inventory_deltas"] = urgent  # reuse, UI can list
        return plan

    if cmd.kind == "query_risk":
        window = int(cmd.days or 7)
        urgent = coach.get_urgent_risks(user_id, window_days=window, limit=50)
        plan["summary"] = f"At-risk inventory over next {window} day(s)"
        plan["inventory_deltas"] = urgent
        return plan

    if cmd.kind == "plan_recipe":
        # Use rescue recipes but bias names
        recs = coach.get_rescue_recipes(user_id, max_recipes=6, lookahead_days=3)
        if cmd.using_items:
            want = {w.lower() for w in cmd.using_items}
            recs = [r for r in recs if any(h.lower() in want for h in r.get("hit_items", []))]
        plan["summary"] = "Recipes that consume at-risk items"
        plan["notes"].append({"count": len(recs)})
        plan["inventory_deltas"] = recs  # UI can render
        return plan

    raise ValueError("Unsupported command.")

# -----------------------------
# Apply
# -----------------------------

def apply(cmd: Command, user_id: int) -> Dict[str, Any]:
    """
    Execute the command; return receipt dict for UI.
    """
    if cmd.kind == "freeze":
        inv = _find_item(user_id, cmd.item or "")
        if not inv:
            raise ValueError("Item not found.")
        qty, unit = _coerce_qty_unit(inv, cmd.qty, cmd.unit)
        ok, msg = coach.apply_freeze(user_id, inv.id, qty, extra_days=int(cmd.extra_days or coach.DEFAULT_FREEZE_EXT_DAYS))
        if not ok:
            raise RuntimeError(msg)
        return {"ok": True, "message": msg}

    if cmd.kind == "use":
        inv = _find_item(user_id, cmd.item or "");  qty, unit = _coerce_qty_unit(inv, cmd.qty, cmd.unit)
        ok, msg = coach.mark_used_now(user_id, inv.id, qty)
        if not ok: raise RuntimeError(msg)
        return {"ok": True, "message": msg}

    if cmd.kind == "throw":
        inv = _find_item(user_id, cmd.item or "");  qty, unit = _coerce_qty_unit(inv, cmd.qty, cmd.unit)
        ok, msg = coach.mark_thrown_now(user_id, inv.id, qty)
        if not ok: raise RuntimeError(msg)
        return {"ok": True, "message": msg}

    if cmd.kind == "add_to_cart":
        if not shop:
            raise RuntimeError("Shopping core not available.")
        # Best-effort call. Your shopping_core should expose add_to_cart.
        try:
            res = shop.add_to_cart(user_id=user_id, store_name=cmd.store, item_name=cmd.item,
                                   quantity=float(cmd.qty or 1.0), unit=cmd.unit or "pcs", note="AI Command")
        except TypeError:
            # alt signature fallback
            res = shop.add_to_cart(user_id, cmd.store, cmd.item, float(cmd.qty or 1.0), cmd.unit or "pcs", "AI Command")
        return {"ok": True, "message": f"Added to {cmd.store}: {cmd.qty:g} {cmd.unit or 'pcs'} {cmd.item}"}

    if cmd.kind in ("query_expiring", "query_risk", "plan_recipe"):
        # Nothing to commit; UI should just render the dry-run
        return {"ok": True, "message": "Query executed."}

    raise ValueError("Unsupported command.")

# -----------------------------
# Automations (v1)
# -----------------------------

def _ensure_rules_table():
    conn = get_connection(); c = conn.cursor()
    try:
        c.execute("""
          CREATE TABLE IF NOT EXISTS ai_rules(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            rule TEXT NOT NULL,       -- e.g. 'if milk < 300 ml then add 1 to Osher Ad'
            enabled INTEGER NOT NULL DEFAULT 1,
            created TEXT NOT NULL
          )
        """)
        conn.commit()
    finally:
        conn.close()

def list_rules(user_id: int) -> List[Tuple[int, str, int]]:
    _ensure_rules_table()
    conn = get_connection(); c = conn.cursor()
    try:
        c.execute("SELECT id, rule, enabled FROM ai_rules WHERE user_id=? ORDER BY id DESC", (user_id,))
        return [(int(r[0]), r[1], int(r[2])) for r in c.fetchall()]
    finally:
        conn.close()

def add_rule(user_id: int, rule_text: str):
    _ensure_rules_table()
    conn = get_connection(); c = conn.cursor()
    try:
        c.execute("INSERT INTO ai_rules(user_id, rule, enabled, created) VALUES (?,?,1, date('now'))",
                  (user_id, rule_text.strip()))
        conn.commit()
    finally:
        conn.close()

def set_rule_enabled(user_id: int, rule_id: int, enabled: bool):
    _ensure_rules_table()
    conn = get_connection(); c = conn.cursor()
    try:
        c.execute("UPDATE ai_rules SET enabled=? WHERE user_id=? AND id=?", (1 if enabled else 0, user_id, rule_id))
        conn.commit()
    finally:
        conn.close()

def delete_rule(user_id: int, rule_id: int):
    _ensure_rules_table()
    conn = get_connection(); c = conn.cursor()
    try:
        c.execute("DELETE FROM ai_rules WHERE user_id=? AND id=?", (user_id, rule_id))
        conn.commit()
    finally:
        conn.close()

def run_automations(user_id: int) -> List[str]:
    """
    Evaluate basic "if <item> < <qty><unit> then add <n> to <store>" rules.
    Rules are deliberately simple and human-readable.
    """
    _ensure_rules_table()
    rows = list_rules(user_id)
    inv = _fetch_inventory(user_id)
    notes: List[str] = []

    pattern = re.compile(
        r"^if\s+(?P<item>[\w\s\-]+)\s*<\s*(?P<th>\d+(?:\.\d+)?)\s*(?P<u>g|ml|pcs|x)?\s*then\s*add\s*(?P<qty>\d+(?:\.\d+)?)\s*(?P<uu>pcs|x|g|ml)?\s*to\s*(?P<store>.+)$",
        re.IGNORECASE
    )

    for rid, rule, enabled in rows:
        if not enabled:
            continue
        m = pattern.match(rule.strip())
        if not m:
            notes.append(f"Skipped invalid rule #{rid}")
            continue
        item = m.group("item").strip()
        th = float(m.group("th"))
        u = _norm_unit(m.group("u") or "pcs")
        add_qty = float(m.group("qty"))
        add_unit = _norm_unit(m.group("uu") or "pcs")
        store = _find_store_name(m.group("store"))

        if not store:
            notes.append(f"Rule #{rid}: unknown store")
            continue

        target = _find_item(user_id, item)
        if not target:
            notes.append(f"Rule #{rid}: item not found")
            continue

        # naive compare in base units
        amt = target.base_amount
        if u == "g" and target.base_unit == "kg":
            amt *= 1000
        if u == "ml" and target.base_unit == "l":
            amt *= 1000

        if amt < th:
            if not shop:
                notes.append(f"Rule #{rid}: shopping core missing")
                continue
            try:
                shop.add_to_cart(user_id=user_id, store_name=store, item_name=target.name,
                                 quantity=add_qty, unit=add_unit, note=f"rule #{rid}")
                notes.append(f"Rule #{rid}: added {add_qty:g} {add_unit} {target.name} to {store}")
            except Exception as e:
                notes.append(f"Rule #{rid}: error {e}")

    return notes
