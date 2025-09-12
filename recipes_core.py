# recipes_core.py
# Core data + business logic for Recipes. No Streamlit UI here.

from __future__ import annotations
import re, json, math, random, difflib, unicodedata
from datetime import date
from typing import Dict, List, Tuple, Optional

from db import get_connection, _today_keys, _compute_step_count

# ----------------------------- Constants --------------------------------------

UNITS = ["pcs", "g", "kg", "mg", "ml", "l"]
BASE_FOR = {"pcs":"pcs", "g":"g", "kg":"g", "mg":"g", "ml":"ml", "l":"ml"}
MULTIPLIER_TO_BASE = {"pcs":1.0, "mg":0.001, "g":1.0, "kg":1000.0, "ml":1.0, "l":1000.0}

DEFAULT_STAPLES = [
    "water","salt","black pepper","olive oil","vegetable oil","sugar",
    "flour","baking powder","baking soda","vinegar","garlic","onion"
]
SAFE_DEFAULT_STAPLES = set(DEFAULT_STAPLES)  # used by the hard-reset helpers

DESCRIPTOR_TOKENS = {
    "breast","thigh","thighs","drumstick","drumsticks","leg","legs",
    "fillet","fillets","tender","tenders","tenderloin","steak","steaks",
    "mince","minced","ground","boneless","skinless","bone","bone-in",
    "fresh","frozen","large","small","sliced","chopped","diced","cubed",
    "whole","half","skin","with","without"
}

ROOT_HINTS = {
    "chicken":{"chicken"},
    "beef":{"beef"},
    "pork":{"pork"},
    "lamb":{"lamb","mutton"},
    "fish":{"fish","salmon","tuna","cod","tilapia","sardine","mackerel","trout"},
    "shrimp":{"shrimp","prawn","prawns"},
    "egg":{"egg","eggs"},
    "rice":{"rice","basmati","jasmine","arborio","sushi"},
    "potato":{"potato","potatoes"},
    "onion":{"onion","onions","shallot","shallots"},
    "garlic":{"garlic"},
    "tomato":{"tomato","tomatoes"},
}

# ----------------------------- Name normalization -----------------------------

_QTY_WORD = re.compile(r"""
    (?:
       \b\d+(?:\.\d+)?\s*(?:kg|g|mg|l|ml|pcs?|piece|pieces|pack|pkt|bag|lb|lbs|oz)\b
      |\b\d+(?:\.\d+)?(?:kg|g|mg|l|ml|pcs?|lb|oz)\b
      |\b\d+\s*(?:x|×)\s*\d+(?:\.\d+)?\b
    )
""", re.I | re.X)

def _strip_qty_markers(s: str) -> str:
    s = re.sub(r"\(.*?\)", " ", s)
    s = _QTY_WORD.sub(" ", s)
    return s

def normalize_name(s: str) -> str:
    if not s:
        return ""
    s = _strip_qty_markers(s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-zA-Z0-9\s]", " ", s).lower()
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > 3 and s.endswith("es"): s = s[:-2]
    elif len(s) > 3 and s.endswith("s"): s = s[:-1]
    return s

def base_tokens(s: str) -> List[str]:
    norm = normalize_name(s)
    toks=[]
    for t in norm.split():
        if not t: continue
        if t in DESCRIPTOR_TOKENS: continue
        if t.isdigit(): continue
        toks.append(t)
    return toks

def root_hint(tokens: List[str]) -> Optional[str]:
    stoks = set(tokens)
    for root, hints in ROOT_HINTS.items():
        if stoks & hints:
            return root
    return tokens[0] if tokens else None

# ----------------------------- Unit conversion --------------------------------

def to_base(amount: float, unit: str) -> Tuple[float, str]:
    u = (unit or "pcs").lower()
    return float(amount or 0.0) * MULTIPLIER_TO_BASE.get(u, 1.0), BASE_FOR.get(u, "pcs")

def from_base(amount_base: float, ui_unit: str) -> float:
    u = (ui_unit or "pcs").lower()
    if u == "kg": return amount_base/1000.0
    if u == "g":  return amount_base
    if u == "mg": return amount_base*1000.0
    if u == "l":  return amount_base/1000.0
    if u == "ml": return amount_base
    return amount_base

# ----------------------------- Schema & cache ---------------------------------

def _table_columns(conn, table: str) -> set:
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    return {r[1] for r in cur.fetchall()}

def _add_column_if_missing(conn, table: str, col: str, ddl: str):
    if col not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")

def ensure_schema():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
      CREATE TABLE IF NOT EXISTS inventory_aliases(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        alias_norm TEXT NOT NULL,
        item_id INTEGER NOT NULL,
        confidence REAL DEFAULT 1.0,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(user_id, alias_norm)
      )
    """)

    c.execute("""
      CREATE TABLE IF NOT EXISTS usage_log(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        item_id INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        quantity REAL NOT NULL,
        unit TEXT NOT NULL,
        step_count INTEGER DEFAULT 0,
        value_shekel REAL DEFAULT 0,
        ts TEXT NOT NULL,
        month_key TEXT NOT NULL
      )
    """)

    c.execute("""
      CREATE TABLE IF NOT EXISTS recipes_catalog(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        default_servings INTEGER DEFAULT 2,
        time_min INTEGER DEFAULT 20,
        difficulty TEXT DEFAULT 'Easy',
        course TEXT, cuisine TEXT, diet TEXT, allergens TEXT, tags TEXT,
        kcal_per_serv REAL DEFAULT 0, protein_g REAL DEFAULT 0, carbs_g REAL DEFAULT 0, fat_g REAL DEFAULT 0,
        rating INTEGER DEFAULT 0, favorite INTEGER DEFAULT 0, notes TEXT, photo TEXT,
        created_at TEXT DEFAULT (datetime('now'))
      )
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS recipes_catalog_components(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL,
        ingredient_item_id INTEGER NOT NULL,
        quantity_base REAL NOT NULL,
        is_staple INTEGER DEFAULT 0,
        is_optional INTEGER DEFAULT 0,
        yield_pct REAL DEFAULT 100,
        wastage_pct REAL DEFAULT 0,
        category TEXT, vendor_sku TEXT, substitutions TEXT, note TEXT
      )
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS recipe_steps(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recipe_id INTEGER NOT NULL,
        position INTEGER NOT NULL,
        text TEXT NOT NULL,
        minutes INTEGER DEFAULT 0,
        equipment TEXT, photo TEXT
      )
    """)
    c.execute("CREATE TABLE IF NOT EXISTS staples(name TEXT PRIMARY KEY)")

    try:
        _add_column_if_missing(conn, "inventory", "base_unit", "TEXT")
        _add_column_if_missing(conn, "inventory", "base_amount", "REAL DEFAULT 0")
        _add_column_if_missing(conn, "inventory", "price_per_base", "REAL DEFAULT 0")
        _add_column_if_missing(conn, "inventory", "total_cost", "REAL DEFAULT 0")
        _add_column_if_missing(conn, "inventory", "used_count", "INTEGER DEFAULT 0")
        _add_column_if_missing(conn, "inventory", "last_used_month", "TEXT")
        _add_column_if_missing(conn, "inventory", "type", "TEXT")
        _add_column_if_missing(conn, "inventory", "stable", "INTEGER DEFAULT 1")
        _add_column_if_missing(conn, "inventory", "expiration", "TEXT")
        conn.commit()
    except Exception:
        conn.rollback()

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM staples")
    if (cur.fetchone()[0] or 0) == 0:
        cur.executemany("INSERT INTO staples(name) VALUES (?)", [(s.lower(),) for s in DEFAULT_STAPLES])
        conn.commit()

    conn.close()

def _cached_staples_raw() -> List[str]:
    conn = get_connection(); c = conn.cursor()
    c.execute("SELECT name FROM staples")
    xs = [r[0].lower() for r in c.fetchall()]
    conn.close()
    return xs

def _cached_inventory_raw(user_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, name, COALESCE(base_unit,'pcs'), COALESCE(base_amount,0),
             COALESCE(price_per_base,0), COALESCE(type,'Other'),
             COALESCE(stable,0), COALESCE(expiration,'2099-12-31'),
             COALESCE(total_cost,0)
      FROM inventory WHERE user_id=? ORDER BY name
    """, (user_id,))
    rows = c.fetchall(); conn.close()
    return rows

cached_staples = _cached_staples_raw
cached_inventory = _cached_inventory_raw
def invalidate_cache(): pass

# ----------------------------- Linking ----------------------------------------

def _alias_lookup(user_id:int, alias_norm:str) -> Optional[Tuple[int,str]]:
    conn=get_connection(); c=conn.cursor()
    c.execute("""
      SELECT ia.item_id, COALESCE(i.base_unit,'pcs')
      FROM inventory_aliases ia
      JOIN inventory i ON i.id=ia.item_id
      WHERE ia.user_id=? AND ia.alias_norm=?""", (user_id, alias_norm))
    row=c.fetchone()
    conn.close()
    if row: return int(row[0]), row[1]
    return None

def _register_alias(user_id:int, alias_norm:str, item_id:int, confidence:float):
    try:
        conn=get_connection(); c=conn.cursor()
        c.execute("""INSERT INTO inventory_aliases(user_id,alias_norm,item_id,confidence)
                     VALUES (?,?,?,?)
                     ON CONFLICT(user_id,alias_norm) DO UPDATE
                     SET item_id=excluded.item_id, confidence=excluded.confidence""",
                  (user_id, alias_norm, int(item_id), float(confidence)))
        conn.commit(); conn.close()
    except Exception:
        pass

def _inventory_index(user_id:int):
    rows=_cached_inventory_raw(user_id)
    by_id = {}
    names = []
    tokens_map = {}
    for rid, nm, bu, amt, ppb, typ, stable, exp, tc in rows:
        by_id[rid]=(rid,nm,bu,amt,ppb,typ,stable,exp,tc)
        names.append((rid, normalize_name(nm)))
        tokens_map[rid]=set(base_tokens(nm))
    return by_id, names, tokens_map

def _ppb_from_row(price_per_base: float, total_cost: float, have_base: float) -> float:
    ppb = float(price_per_base or 0.0)
    if ppb > 0: return ppb
    if float(total_cost or 0) > 0 and float(have_base or 0) > 0:
        return float(total_cost) / float(have_base)
    return 0.0

def link_inventory(user_id:int, name:str, unit_hint:str=None) -> Optional[Tuple[int,str]]:
    if not name:
        return None
    alias = normalize_name(name)

    ali = _alias_lookup(user_id, alias)
    ali_id, ali_unit = ali if ali else (None, None)

    inv_by_id, inv_names, inv_tokens = _inventory_index(user_id)

    def unit_compat(bu: str) -> bool:
        if not unit_hint: return False
        return BASE_FOR.get((unit_hint or "pcs").lower(),"pcs") == BASE_FOR.get((bu or "pcs").lower(),"pcs")

    q_tokens = base_tokens(name)
    q_root = root_hint(q_tokens)
    alias_noqty = normalize_name(name)

    best_id=None
    best_score=-1.0

    for iid, inv_norm in inv_names:
        bu   = inv_by_id[iid][2]
        have = float(inv_by_id[iid][3] or 0.0)
        typ  = (inv_by_id[iid][5] or "Other") or "Other"
        toks = inv_tokens[iid]

        inter = len(set(q_tokens) & toks)
        union = len(set(q_tokens) | toks) or 1
        sim = inter / union

        if q_root and q_root in toks:
            sim = max(sim, 0.92)
        if alias_noqty == inv_norm:
            sim = max(sim, 0.98)
        if alias_noqty in inv_norm or inv_norm in alias_noqty:
            sim = max(sim, 0.95)

        if have > 0: sim += 0.08
        if unit_compat(bu): sim += 0.03
        if typ and typ.lower() != "other": sim += 0.02

        if sim > best_score:
            best_score = sim; best_id = iid

    if best_id is None or best_score < 0.85:
        if ali_id is not None:
            _register_alias(user_id, alias, ali_id, 0.80)
            return ali_id, ali_unit
        return None

    _register_alias(user_id, alias, best_id, float(min(best_score, 1.0)))
    return best_id, inv_by_id[best_id][2]

# ----------------------------- Data access ------------------------------------

def get_recipes(user_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, title, COALESCE(default_servings,2), COALESCE(time_min,20), COALESCE(difficulty,'Easy'),
             COALESCE(tags,''), COALESCE(cuisine,''), COALESCE(diet,''), COALESCE(allergens,''), COALESCE(photo,''),
             COALESCE(rating,0), COALESCE(favorite,0), COALESCE(course,'')
      FROM recipes_catalog
      WHERE user_id=?
      ORDER BY created_at DESC, id DESC
    """, (user_id,))
    rows = c.fetchall(); conn.close()
    return rows

def _recipe_user_id(recipe_id:int) -> Optional[int]:
    conn=get_connection(); c=conn.cursor()
    c.execute("SELECT user_id FROM recipes_catalog WHERE id=?", (recipe_id,))
    row=c.fetchone(); conn.close()
    return int(row[0]) if row else None

def get_recipe_meta(recipe_id:int):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT title, COALESCE(default_servings,2), COALESCE(time_min,20), COALESCE(difficulty,'Easy'),
             COALESCE(course,''), COALESCE(cuisine,''), COALESCE(diet,''), COALESCE(allergens,''), COALESCE(tags,''),
             COALESCE(kcal_per_serv,0), COALESCE(protein_g,0), COALESCE(carbs_g,0), COALESCE(fat_g,0),
             COALESCE(rating,0), COALESCE(favorite,0), COALESCE(notes,''), COALESCE(photo,'')
      FROM recipes_catalog WHERE id=?
    """, (recipe_id,))
    row = c.fetchone(); conn.close()
    return row

def get_recipe_steps(recipe_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT id, position, text, COALESCE(minutes,0), COALESCE(equipment,''), COALESCE(photo,'')
      FROM recipe_steps WHERE recipe_id=? ORDER BY position
    """, (recipe_id,))
    rows = c.fetchall(); conn.close()
    return rows

def get_recipe_components(recipe_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute("""
      SELECT rcc.id, rcc.ingredient_item_id, i.name, COALESCE(i.base_unit,'pcs'),
             COALESCE(i.base_amount,0), COALESCE(i.price_per_base,0), COALESCE(i.type,'Other'),
             rcc.quantity_base, COALESCE(rcc.is_staple,0), COALESCE(rcc.is_optional,0),
             COALESCE(rcc.yield_pct,100), COALESCE(rcc.wastage_pct,0), COALESCE(rcc.category,''), COALESCE(rcc.vendor_sku,''),
             COALESCE(rcc.substitutions,''), COALESCE(rcc.note,''), COALESCE(i.total_cost,0)
      FROM recipes_catalog_components rcc
      LEFT JOIN inventory i ON i.id = rcc.ingredient_item_id
      WHERE rcc.recipe_id=? ORDER BY i.name
    """, (recipe_id,))
    rows = c.fetchall(); conn.close()
    return rows

# ----------------------------- Coverage / Cost --------------------------------

def _is_staple_name(name: str, staples_list: Optional[List[str]] = None) -> bool:
    staples = set(normalize_name(s) for s in (staples_list or _cached_staples_raw()))
    return normalize_name(name or "") in staples

def coverage_for_recipe(recipe_id: int, servings: int) -> Dict:
    comps = get_recipe_components(recipe_id)
    if not comps:
        return {'coverage_pct':0,'status':'err','items':[],'cost_total':0.0,'cost_per_portion':0.0,'max_cookable':0}
    meta = get_recipe_meta(recipe_id)
    default_serv = int(meta[1] or 2) if meta else 2
    scale = max(0.001, float(servings)/max(1,default_serv))
    user_id = _recipe_user_id(recipe_id)

    total_need=0.0; total_have=0.0; total_cost=0.0; limiting=[]; items=[]
    staples_list=_cached_staples_raw()

    for (_cid, ing_id, nm, bu, have_base, ppb, _inv_type,
         q_base_def, is_staple, is_opt, yield_pct, wastage_pct, cat, sku, subs_json, note, total_cost_row) in comps:

        needed_raw = float(q_base_def or 0.0) * scale
        needed_with_waste = needed_raw * (100.0 + float(wastage_pct or 0.0))/100.0
        effective_need = needed_with_waste / max(0.01, float(yield_pct or 100.0)/100.0)

        # staple only if both the flag AND the staples list say so
        staple = (bool(is_staple) and _is_staple_name(nm or "", staples_list))

        have = float(have_base or 0.0)
        unit_price = _ppb_from_row(ppb, total_cost_row, have_base)
        alt_used = False

        if not staple and user_id is not None and have <= 1e-9:
            alt = link_inventory(user_id, nm, unit_hint=bu)
            if alt and int(alt[0]) != int(ing_id or 0):
                conn=get_connection(); c=conn.cursor()
                c.execute("""SELECT COALESCE(base_amount,0), COALESCE(price_per_base,0), COALESCE(total_cost,0)
                             FROM inventory WHERE id=?""", (int(alt[0]),))
                rr=c.fetchone(); conn.close()
                if rr:
                    have_alt, ppb_alt, tc_alt = float(rr[0] or 0.0), float(rr[1] or 0.0), float(rr[2] or 0.0)
                    if have_alt > have:
                        have = have_alt
                        unit_price = _ppb_from_row(ppb_alt, tc_alt, have_alt)
                        alt_used = True

        status="staple"; short=0.0
        if not staple:
            if effective_need <= have + 1e-9:
                status="ok"; total_have += effective_need
            elif have > 0:
                status="warn"
            else:
                status="err"
            short=max(0.0, effective_need - have)
        else:
            total_have += effective_need

        total_need += effective_need
        total_cost += effective_need * unit_price
        if not staple and effective_need>0:
            limiting.append(have/effective_need if effective_need>0 else 0)
        items.append({
            "name": nm or "—", "unit": bu or "pcs", "need_base": effective_need, "have_base": have,
            "short_base": short, "staple": staple, "optional": bool(is_opt), "status": status,
            "category": cat or "", "vendor_sku": sku or "", "subs": subs_json or "", "alt_used": alt_used
        })

    cov = 0 if total_need<=0 else int(round(min(1.0, total_have/total_need)*100))
    status = "ok" if cov==100 else ("warn" if cov>=60 else "err")
    max_cookable = int(math.floor(min(limiting) if limiting else 0))
    return {"coverage_pct": cov, "status": status, "items": items,
            "cost_total": round(total_cost,2), "cost_per_portion": round(total_cost/max(1,servings),2),
            "max_cookable": max_cookable}

# ----------------------------- Cooking ----------------------------------------

def cook_recipe(user_id:int, recipe_id:int, servings:int, deduct_optional:bool=True)->Tuple[bool,str]:
    cov=coverage_for_recipe(recipe_id, servings)
    need_ok = cov["coverage_pct"]==100 or (deduct_optional and all(i["optional"] or i["staple"] or i["status"]=="ok" for i in cov["items"]))
    if not need_ok:
        return False, "Not enough ingredients."

    meta = get_recipe_meta(recipe_id)
    if not meta: return False, "Recipe not found"
    dsv=int(meta[1] or 2); title=meta[0]
    scale=max(0.001,float(servings)/max(1,dsv))

    comps=get_recipe_components(recipe_id)
    conn=get_connection(); c=conn.cursor()
    ts, mk = _today_keys()

    try:
        c.execute("BEGIN IMMEDIATE")
        for (_cid, ing_id, nm, bu, _have, _ppb, _inv_type,
             q_base_def, is_staple, is_opt, yield_pct, wastage_pct, _cat, _sku, _subs, _note, _tc) in comps:

            staple = (bool(is_staple) and _is_staple_name(nm or ""))
            if staple: continue
            if bool(is_opt) and not deduct_optional: continue

            needed_raw=float(q_base_def or 0.0)*scale
            need = (needed_raw * (100.0 + float(wastage_pct or 0.0))/100.0) / max(0.01, float(yield_pct or 100)/100.0)
            if need<=0: continue

            c.execute("SELECT id, COALESCE(base_amount,0), COALESCE(base_unit,'pcs'), COALESCE(used_count,0) FROM inventory WHERE id=?", (ing_id,))
            r=c.fetchone()
            if not r: raise RuntimeError(f"Missing inventory item: {nm}")
            cur_id, cur_amt, base_unit, used_count = int(r[0]), float(r[1] or 0.0), (r[2] or bu), int(r[3] or 0)

            if cur_amt + 1e-9 < need:
                alt = link_inventory(user_id, nm, unit_hint=bu)
                if alt and int(alt[0]) != cur_id:
                    c.execute("SELECT COALESCE(base_amount,0), COALESCE(base_unit,'pcs'), COALESCE(used_count,0) FROM inventory WHERE id=?", (int(alt[0]),))
                    rr=c.fetchone()
                    if rr and float(rr[0] or 0.0) >= need - 1e-9:
                        c.execute("UPDATE recipes_catalog_components SET ingredient_item_id=? WHERE id=?", (int(alt[0]), _cid))
                        cur_id = int(alt[0]); cur_amt = float(rr[0] or 0.0); base_unit = rr[1] or base_unit; used_count = int(rr[2] or 0)

            if cur_amt + 1e-9 < need:
                if bool(is_opt):  # optional shortfalls are skipped
                    continue
                raise RuntimeError(f"Insufficient {nm}: need {need:.2f} {base_unit}, have {cur_amt:.2f} {base_unit}")

            new_amt=cur_amt-need
            step=_compute_step_count(need, base_unit)
            c.execute("UPDATE inventory SET base_amount=?, used_count=?, last_used_month=strftime('%Y-%m','now') WHERE id=?",
                      (new_amt, used_count + int(step), cur_id))
            c.execute("""
              INSERT INTO usage_log (user_id,item_id,event_type,quantity,unit,step_count,value_shekel,ts,month_key)
              VALUES (?, ?, 'used', ?, ?, ?, 0.0, ?, ?)""",
              (user_id, cur_id, float(need), base_unit, int(step), ts, mk))
        conn.commit()
    except Exception as e:
        conn.rollback(); conn.close()
        return False, f"Cook failed: {e}"
    conn.close()
    return True, f"Cooked {title} for {servings} serving(s)."

# ----------------------------- Create / persist --------------------------------

def create_recipe_atomic(user_id:int, meta:dict, components:List[dict], steps:List[dict]) -> int:
    conn=get_connection(); c=conn.cursor()
    try:
        c.execute("BEGIN IMMEDIATE")
        c.execute("""INSERT INTO recipes_catalog(user_id,title,default_servings,time_min,difficulty,course,cuisine,diet,allergens,tags,
                     kcal_per_serv,protein_g,carbs_g,fat_g,notes,photo)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)""",
                  (user_id, meta["title"].strip(), int(meta["default_servings"]), int(meta["time_min"]), meta["difficulty"],
                   meta.get("course",""), meta.get("cuisine",""), meta.get("diet",""), meta.get("allergens",""),
                   meta.get("tags",""), float(meta.get("kcal",0)), float(meta.get("protein",0)),
                   float(meta.get("carbs",0)), float(meta.get("fat",0)), meta.get("notes","")))
        rid=int(c.lastrowid)

        staples=set(normalize_name(s) for s in _cached_staples_raw())
        for comp in components:
            if comp.get("inv_id"):
                ing_id=int(comp["inv_id"])
                c.execute("SELECT COALESCE(base_unit,'pcs') FROM inventory WHERE id=?", (ing_id,))
                bu=(c.fetchone() or ["pcs"])[0]
                qty_ui=float(comp.get("qty_per_serv",0))*int(meta["default_servings"])
                need_base,_=to_base(qty_ui, bu)
            else:
                nm=(comp.get("name") or "").strip()
                unit=(comp.get("unit") or "pcs")
                guess=link_inventory(user_id, nm, unit_hint=unit)
                if guess:
                    ing_id, bu = guess
                else:
                    bu = unit if unit in BASE_FOR else "pcs"
                    c.execute("""INSERT INTO inventory(user_id,name,base_unit,base_amount,price_per_base,total_cost,type,stable)
                                 VALUES (?,?,?,?,0,0,'Other',1)""",
                              (user_id, nm, bu, 0.0))
                    ing_id=int(c.lastrowid)
                    _register_alias(user_id, normalize_name(nm), ing_id, 0.80)
                qty_ui=float(comp.get("qty_per_serv",0))*int(meta["default_servings"])
                need_base,_=to_base(qty_ui, bu)

            is_staple = 1 if (comp.get("staple") and normalize_name(comp.get("name","")) in staples) else 0
            c.execute("""INSERT INTO recipes_catalog_components
                         (recipe_id,ingredient_item_id,quantity_base,is_staple,is_optional,yield_pct,wastage_pct,category,vendor_sku,substitutions,note)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                      (rid, ing_id, float(need_base),
                       is_staple,
                       1 if comp.get("optional") else 0,
                       float(comp.get("yield_pct",100)),
                       float(comp.get("wastage_pct",0)),
                       comp.get("category",""),
                       comp.get("vendor_sku",""),
                       json.dumps(comp.get("subs",[])),
                       comp.get("note","")))
        for i, step in enumerate(steps, start=1):
            equip = step.get("equipment",[])
            c.execute("""INSERT INTO recipe_steps(recipe_id,position,text,minutes,equipment,photo)
                         VALUES (?,?,?,?,?,?)""",
                      (rid, i, (step.get("text","") or "").strip(), int(step.get("minutes",0)),
                       ",".join(equip), step.get("photo","")))
        conn.commit()
    except Exception:
        conn.rollback(); conn.close(); raise
    conn.close()
    return rid

# ----------------------------- AI / persist AI --------------------------------

def ai_generate_recipe(user_id:int, constraints:str)->Optional[dict]:
    inv=_cached_inventory_raw(user_id)
    picks=[r for r in inv if (r[3] or 0)>0]
    random.shuffle(picks); picks=picks[:min(8, max(3, len(picks)//2 or 3))]
    title=f"{random.choice(['Quick','Rustic','Weeknight','Comfort'])} " + (picks[0][1] if picks else "Pantry Dish")
    components=[]
    for pid, name, bu, amt, _, typ, _, _, _tc in picks:
        per=150.0 if (bu or "pcs") in ("g","ml") else 1.0
        components.append({"name":name,"unit":bu or "pcs","quantity_per_serving":per,"staple":False,"optional":False,"yield_pct":100,"wastage_pct":0})
    steps=[{"text":"Prep ingredients.","minutes":5,"equipment":["knife","board"]},
           {"text":"Cook until done.","minutes":15,"equipment":["pan"]}]
    return {"title":title,"default_servings":2,"time_min":20,"difficulty":"Easy","course":"Dinner",
            "cuisine":"","diet":"","tags":["Auto"],"allergens":[],
            "kcal_per_serv":450,"protein_g":25,"carbs_g":40,"fat_g":18,
            "steps":steps,"components":components}

def persist_ai_recipe(user_id:int, data:dict)->int:
    meta = {
        "title": data.get("title","New Recipe"),
        "default_servings": int(data.get("default_servings") or 2),
        "time_min": int(data.get("time_min") or 20),
        "difficulty": data.get("difficulty") or "Easy",
        "course": data.get("course",""),
        "cuisine": data.get("cuisine",""),
        "diet": data.get("diet",""),
        "allergens": ",".join(data.get("allergens") or []),
        "tags": ",".join(data.get("tags") or []),
        "kcal": float(data.get("kcal_per_serv") or 0),
        "protein": float(data.get("protein_g") or 0),
        "carbs": float(data.get("carbs_g") or 0),
        "fat": float(data.get("fat_g") or 0),
        "notes": data.get("notes",""),
    }
    comps=[]
    for comp in data.get("components") or []:
        nm=(comp.get("name") or "").strip()
        u=(comp.get("unit") or "pcs").lower()
        q=float(comp.get("quantity_per_serving") or 0)
        if not nm or q<=0: continue
        comps.append({
            "name": nm, "unit": u, "qty_per_serv": q,
            "staple": bool(comp.get("staple",False)),
            "optional": bool(comp.get("optional",False)),
            "yield_pct": float(comp.get("yield_pct",100)),
            "wastage_pct": float(comp.get("wastage_pct",0)),
            "category":"", "vendor_sku":"", "subs": [], "note":""
        })
    steps=[]
    for step in data.get("steps") or []:
        steps.append({"text": (step.get("text","") or ""), "minutes": int(step.get("minutes",0)),
                      "equipment": step.get("equipment",[]), "photo": ""})
    return create_recipe_atomic(user_id, meta, comps, steps)

# ----------------------------- Repairs / debug --------------------------------

def set_component_staple(component_id:int, state:bool):
    conn=get_connection()
    conn.execute("UPDATE recipes_catalog_components SET is_staple=? WHERE id=?",
                 (1 if state else 0, int(component_id)))
    conn.commit(); conn.close()

def recompute_staples_for_user(user_id:int)->int:
    staples=set(normalize_name(s) for s in _cached_staples_raw())
    conn=get_connection(); c=conn.cursor()
    c.execute("""SELECT rcc.id, i.name
                 FROM recipes_catalog_components rcc
                 JOIN recipes_catalog r ON r.id=rcc.recipe_id
                 JOIN inventory i ON i.id=rcc.ingredient_item_id
                 WHERE r.user_id=?""",(user_id,))
    rows=c.fetchall()
    for cid, nm in rows:
        val=1 if normalize_name(nm) in staples else 0
        c.execute("UPDATE recipes_catalog_components SET is_staple=? WHERE id=?", (val, cid))
    conn.commit(); conn.close()
    return len(rows)

def recompute_staples_for_recipe(recipe_id:int) -> int:
    staples=set(normalize_name(s) for s in _cached_staples_raw())
    conn=get_connection(); c=conn.cursor()
    c.execute("""SELECT rcc.id, i.name
                 FROM recipes_catalog_components rcc
                 JOIN inventory i ON i.id=rcc.ingredient_item_id
                 WHERE rcc.recipe_id=?""", (recipe_id,))
    rows=c.fetchall()
    for cid, nm in rows:
        c.execute("UPDATE recipes_catalog_components SET is_staple=? WHERE id=?",
                  (1 if normalize_name(nm) in staples else 0, cid))
    conn.commit(); conn.close()
    return len(rows)

def reset_recipe_staples_to_defaults(recipe_id:int) -> int:
    """Force staple flags to a tiny safe set regardless of the Staples table."""
    safe = set(normalize_name(s) for s in SAFE_DEFAULT_STAPLES)
    conn=get_connection(); c=conn.cursor()
    c.execute("""SELECT rcc.id, i.name
                 FROM recipes_catalog_components rcc
                 JOIN inventory i ON i.id=rcc.ingredient_item_id
                 WHERE rcc.recipe_id=?""", (recipe_id,))
    rows=c.fetchall(); touched=0
    for cid, nm in rows:
        new_val = 1 if normalize_name(nm) in safe else 0
        c.execute("UPDATE recipes_catalog_components SET is_staple=? WHERE id=?", (new_val, cid))
        touched += 1
    conn.commit(); conn.close()
    return touched

def reset_all_staples_to_defaults(user_id:int) -> int:
    safe = set(normalize_name(s) for s in SAFE_DEFAULT_STAPLES)
    conn=get_connection(); c=conn.cursor()
    c.execute("""SELECT rcc.id, i.name
                 FROM recipes_catalog_components rcc
                 JOIN recipes_catalog r ON r.id=rcc.recipe_id
                 JOIN inventory i ON i.id=rcc.ingredient_item_id
                 WHERE r.user_id=?""",(user_id,))
    rows=c.fetchall(); touched=0
    for cid, nm in rows:
        new_val = 1 if normalize_name(nm) in safe else 0
        c.execute("UPDATE recipes_catalog_components SET is_staple=? WHERE id=?", (new_val, cid))
        touched += 1
    conn.commit(); conn.close()
    return touched

def repair_links_for_recipe(recipe_id:int) -> int:
    """Relink components to best stocked inventory rows permanently."""
    user_id = _recipe_user_id(recipe_id)
    if user_id is None:
        return 0
    comps = get_recipe_components(recipe_id)
    changed = 0
    conn=get_connection(); c=conn.cursor()
    try:
        c.execute("BEGIN IMMEDIATE")
        for (_cid, ing_id, nm, bu, have, _ppb, _inv_type,
             _q, is_staple, _is_opt, _y, _w, _cat, _sku, _subs, _note, _tc) in comps:
            guess = link_inventory(user_id, nm, unit_hint=bu)
            if not guess: continue
            new_id = int(guess[0])
            if new_id != int(ing_id or 0):
                c.execute("SELECT COALESCE(base_amount,0) FROM inventory WHERE id=?", (new_id,))
                rr=c.fetchone()
                if rr and float(rr[0] or 0.0) > float(have or 0.0):
                    c.execute("UPDATE recipes_catalog_components SET ingredient_item_id=? WHERE id=?", (new_id, _cid))
                    changed += 1
        conn.commit()
    except Exception:
        conn.rollback(); changed=0
    finally:
        conn.close()
    return changed

def diagnose_recipe_links(recipe_id:int) -> List[Dict]:
    """For UI debug: show current link, stock, and best-alt candidate for each line."""
    user_id = _recipe_user_id(recipe_id)
    out=[]
    if user_id is None: return out
    comps=get_recipe_components(recipe_id)
    for (_cid, ing_id, nm, bu, have, _ppb, _inv_type,
         q_base_def, is_staple, is_opt, y, wst, cat, sku, subs, note, tc) in comps:
        alt = link_inventory(user_id, nm, unit_hint=bu)
        alt_id = int(alt[0]) if alt else None
        out.append({
            "component_id": _cid,
            "name": nm,
            "linked_item_id": int(ing_id or 0),
            "linked_have": float(have or 0.0),
            "alt_item_id": alt_id,
            "alt_is_different": bool(alt_id and int(alt_id)!=int(ing_id or 0))
        })
    return out
