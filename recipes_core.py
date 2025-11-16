# recipes_core.py
# Core logic for Recipes. Compatible with RecipesPage.py (recipes_catalog schema).
# Inventory schema tolerant: prefers 'inventory', falls back to 'items', adapts to columns present.
# Includes nutrition auto-fill for AI drafts, safe step-count wrapper, create-or-link inventory for manual rows,
# and delete_recipe.
#
# Lock-avoidance upgrades:
#   • Resolve/link/create inventory for manual rows BEFORE the main transaction
#   • One short BEGIN IMMEDIATE per operation, wrapped in a light retry on SQLITE_BUSY
#   • No writes to other tables inside an open write TX unless that’s the one TX we’re doing

from __future__ import annotations
import os, re, json, math, random, difflib, unicodedata, sqlite3, time
from typing import Dict, List, Tuple, Optional

from db import get_connection, _today_keys, _compute_step_count

# ----------------------------- tiny transaction retry -------------------------

def _txn_retry(begin_sql: str, work_fn, max_wait_ms: int = 3000, sleep_ms: int = 60):
    """
    Run work_fn(conn, cursor) inside a single transaction started with begin_sql.
    Retries on SQLITE_BUSY/locked up to max_wait_ms total.
    """
    deadline = time.time() + (max_wait_ms / 1000.0)
    last_exc = None
    while time.time() < deadline:
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute(begin_sql)
            work_fn(conn, cur)
            conn.commit()
            conn.close()
            return
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "locked" in msg or "busy" in msg:
                try:
                    conn.rollback()
                except Exception:
                    pass
                conn.close()
                last_exc = e
                time.sleep(sleep_ms / 1000.0)
                continue
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            raise
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            conn.close()
            raise
    # exhausted retries
    if last_exc:
        raise last_exc
    raise RuntimeError("Transaction retry exhausted without specific error.")

# ----------------------------- Safe wrapper for step counter ------------------

def _safe_step_count(user_id: int, unit: str | None = None) -> int:
    """Support both _compute_step_count(user_id, unit) and old _compute_step_count(user_id)."""
    try:
        v = _compute_step_count(user_id, unit)  # new signature
        return int(v or 0)
    except TypeError:
        try:
            v = _compute_step_count(user_id)     # legacy signature
            return int(v or 0)
        except Exception:
            return 0
    except Exception:
        return 0

# ----------------------------- Constants --------------------------------------

UNITS = ["pcs", "g", "kg", "mg", "ml", "l"]
BASE_FOR = {"pcs":"pcs", "g":"g", "kg":"g", "mg":"g", "ml":"ml", "l":"ml"}
MULTIPLIER_TO_BASE = {"pcs":1.0, "mg":0.001, "g":1.0, "kg":1000.0, "ml":1.0, "l":1000.0}

DEFAULT_STAPLES = [
    "water","salt","black pepper","olive oil","vegetable oil","sugar",
    "flour","baking powder","baking soda","vinegar","garlic","onion","yeast","tomato sauce"
]
SAFE_DEFAULT_STAPLES = set(DEFAULT_STAPLES)

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

def _strip_punct(s: str) -> str:
    s = s.replace("'", " ").replace('"', " ")
    s = re.sub(r"[^a-z0-9\s]+", " ", s)
    return s

def normalize_name(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = _strip_qty_markers(s)
    s = _strip_punct(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def base_tokens(s: str) -> List[str]:
    s = normalize_name(s)
    return [t for t in s.split(" ") if t]

# ----------------------------- Staples (Settings tab) -------------------------

def _cached_staples_raw() -> list[str]:
    """Return staple names from DB table 'staples' if present; else defaults."""
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT name FROM staples ORDER BY name")
        rows = cur.fetchall()
        conn.close()
        names = [r[0] for r in rows if r and r[0]]
        return names or list(DEFAULT_STAPLES)
    except Exception:
        return list(DEFAULT_STAPLES)

# Optional alias
cached_staples = _cached_staples_raw

# ----------------------------- DB Introspection -------------------------------

_INV_SCHEMA_CACHE: Optional[dict] = None

def _table_exists(conn, name: str) -> bool:
    c = conn.cursor()
    c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,))
    return c.fetchone() is not None

def _columns(conn, table: str) -> set:
    c = conn.cursor()
    try:
        c.execute(f"PRAGMA table_info({table})")
        return {r[1] for r in c.fetchall()}
    except sqlite3.OperationalError:
        return set()

def _inventory_schema() -> dict:
    """Detect inventory table and available column names."""
    global _INV_SCHEMA_CACHE
    if _INV_SCHEMA_CACHE is not None:
        return _INV_SCHEMA_CACHE

    conn = get_connection()
    table = "inventory" if _table_exists(conn, "inventory") else ("items" if _table_exists(conn, "items") else None)

    if not table:
        conn.close()
        _INV_SCHEMA_CACHE = {
            "table": None,
            "cols": set(),
            "id": "id",
            "user_id": "user_id",
            "name": "name",
            "base_unit": "base_unit",
            "amount": "base_amount",
            "price_per_base": "price_per_base",
            "type": "type",
            "stable": "stable",
            "expires": "expiration",
            "token_cache": None,
            "total_cost": "total_cost",
            "used_count": "used_count",
        }
        return _INV_SCHEMA_CACHE

    cols = _columns(conn, table)
    conn.close()

    def pick(*options):
        for o in options:
            if o and o in cols:
                return o
        return None

    _INV_SCHEMA_CACHE = {
        "table": table,
        "cols": cols,
        "id": pick("id"),
        "user_id": pick("user_id"),
        "name": pick("name"),
        "base_unit": pick("base_unit", "unit", "uom"),
        "amount": pick("base_amount", "quantity_in_base", "qty_base", "amount"),
        "price_per_base": pick("price_per_base", "price_per_unit", "ppu"),
        "type": pick("type", "category"),
        "stable": pick("stable", "is_stable"),
        "expires": pick("expiration", "expires_at"),
        "token_cache": pick("token_cache"),
        "total_cost": pick("total_cost"),
        "used_count": pick("used_count", "usage_count"),
    }
    return _INV_SCHEMA_CACHE

# ----------------------------- Inventory access -------------------------------

# Normalized row shape:
# (id, name, base_unit, have_base, price_per_base, inv_type, stable, expires, token_cache, total_cost, used_count)
_INV_CACHE: Dict[int, List[Tuple]] = {}

def _read_inventory_row(item_id: int) -> dict:
    sch = _inventory_schema()
    if not sch["table"]:
        return {"id": item_id, "name": "", "base_unit": "pcs", "amount": 0.0, "price_per_base": 0.0,
                "type": "Other", "stable": 0, "expires": "", "token_cache": "", "total_cost": 0.0, "used_count": 0}

    n = lambda k: sch[k] if sch[k] in (sch["cols"] or set()) else None
    cols = []
    for k in ("id","name","base_unit","amount","price_per_base","type","stable","expires","token_cache","total_cost","used_count"):
        ck = n(k)
        if ck: cols.append(ck)

    conn = get_connection(); c = conn.cursor()
    try:
        c.execute(f"SELECT {', '.join(cols)} FROM {sch['table']} WHERE {sch['id']}=?", (item_id,))
        row = c.fetchone()
    except sqlite3.OperationalError:
        row = None
    conn.close()

    data = {"id": item_id, "name": "", "base_unit": "pcs", "amount": 0.0, "price_per_base": 0.0,
            "type": "Other", "stable": 0, "expires": "", "token_cache": "", "total_cost": 0.0, "used_count": 0}
    if row:
        m = dict(zip(cols, row))
        data.update({
            "name": m.get(sch["name"], "") if sch["name"] else "",
            "base_unit": m.get(sch["base_unit"], "pcs") if sch["base_unit"] else "pcs",
            "amount": float(m.get(sch["amount"], 0.0)) if sch["amount"] else 0.0,
            "price_per_base": float(m.get(sch["price_per_base"], 0.0)) if sch["price_per_base"] else 0.0,
            "type": m.get(sch["type"], "Other") if sch["type"] else "Other",
            "stable": int(m.get(sch["stable"], 0)) if sch["stable"] else 0,
            "expires": m.get(sch["expires"], "") if sch["expires"] else "",
            "token_cache": m.get(sch["token_cache"], "") if sch["token_cache"] else "",
            "total_cost": float(m.get(sch["total_cost"], 0.0)) if sch["total_cost"] else 0.0,
            "used_count": int(m.get(sch["used_count"], 0)) if sch["used_count"] else 0,
        })
    return data

def _cached_inventory_raw(user_id: int) -> List[Tuple]:
    if user_id in _INV_CACHE:
        return _INV_CACHE[user_id]

    sch = _inventory_schema()
    if not sch["table"]:
        _INV_CACHE[user_id] = []
        return []

    cols_order = []
    def addcol(name):
        if sch[name] and sch[name] in sch["cols"]:
            cols_order.append(sch[name])

    for key in ("id","name","base_unit","amount","price_per_base","type","stable","expires","token_cache","total_cost","used_count"):
        addcol(key)

    where = ""
    params = ()
    if sch["user_id"] and sch["user_id"] in sch["cols"]:
        where = f"WHERE {sch['user_id']}=?"
        params = (user_id,)

    conn = get_connection(); c = conn.cursor()
    rows = []
    try:
        select_cols = ", ".join([cname for cname in cols_order if cname])
        c.execute(f"SELECT {select_cols} FROM {sch['table']} {where} ORDER BY {sch['id']} DESC", params)
        pulled = c.fetchall()
        for r in pulled:
            m = dict(zip([cn for cn in cols_order if cn], r))
            tup = (
                int(m.get(sch["id"], 0)),
                m.get(sch["name"], "") or "",
                m.get(sch["base_unit"], "pcs") or "pcs",
                float(m.get(sch["amount"], 0.0) or 0.0),
                float(m.get(sch["price_per_base"], 0.0) or 0.0),
                m.get(sch["type"], "Other") or "Other",
                int(m.get(sch["stable"], 0) or 0),
                m.get(sch["expires"], "") or "",
                m.get(sch["token_cache"], "") or "",
                float(m.get(sch["total_cost"], 0.0) or 0.0),
                int(m.get(sch["used_count"], 0) or 0),
            )
            rows.append(tup)
    except sqlite3.OperationalError:
        rows = []
    conn.close()

    _INV_CACHE[user_id] = rows
    return rows

cached_inventory = _cached_inventory_raw

def _inventory_index(user_id:int):
    rows=_cached_inventory_raw(user_id)
    by_id = {}; names = []; tokens_map = {}
    for rid, nm, bu, amt, ppb, typ, stable, exp, tc, tcst, used in rows:
        by_id[rid]=(rid,nm,bu,amt,ppb,typ,stable,exp,tc,tcst,used)
        names.append((rid, normalize_name(nm or "")))
        tokens_map[rid]=set(base_tokens(nm or ""))
    return by_id, names, tokens_map

# ----------------------------- Linking / ensure item --------------------------

def link_inventory(user_id:int, name:str, unit_hint:str=None) -> Optional[Tuple[int,str]]:
    if not name:
        return None

    inv_by_id, inv_names, inv_tokens = _inventory_index(user_id)

    def unit_compat(bu: str) -> bool:
        if not unit_hint: return False
        return BASE_FOR.get((unit_hint or "pcs").lower(),"pcs") == BASE_FOR.get((bu or "pcs").lower(),"pcs")

    q_tokens = base_tokens(name)
    alias_noqty = normalize_name(name)

    best_id=None; best_score=-1.0
    for iid, inv_norm in inv_names:
        bu   = inv_by_id[iid][2]
        have = float(inv_by_id[iid][3] or 0.0)
        typ  = (inv_by_id[iid][5] or "Other") or "Other"
        toks = inv_tokens[iid]

        inter = len(set(q_tokens) & toks)
        union = len(set(q_tokens) | toks) or 1
        sim = inter / union

        if alias_noqty == inv_norm:   sim = max(sim, 0.98)
        if alias_noqty in inv_norm or inv_norm in alias_noqty: sim = max(sim, 0.95)
        if have > 0: sim += 0.08
        if unit_compat(bu): sim += 0.03
        if typ and typ.lower() != "other": sim += 0.02

        if sim > best_score:
            best_score = sim; best_id = iid

    if best_id is None or best_score < 0.85:
        return None

    return best_id, inv_by_id[best_id][2]

def _ensure_inventory_item(user_id:int, name:str, unit_hint:str="pcs") -> Tuple[int,str]:
    """
    Create (or reuse) an inventory row for a brand-new manual ingredient,
    returning (id, base_unit). Never returns None.
    """
    sch = _inventory_schema()
    if not sch["table"]:
        raise RuntimeError("Inventory table not found; cannot create ingredient link.")

    conn = get_connection(); c = conn.cursor()
    try:
        if sch["user_id"] and sch["name"]:
            c.execute(f"SELECT {sch['id']}, {sch['base_unit'] or 'NULL'} FROM {sch['table']} WHERE {sch['user_id']}=? AND LOWER({sch['name']})=LOWER(?) LIMIT 1",
                      (user_id, name))
            r = c.fetchone()
            if r:
                conn.close()
                return int(r[0]), (r[1] or unit_hint or "pcs")

        cols_vals = {}
        if sch["user_id"]:                  cols_vals[sch["user_id"]] = user_id
        if sch["name"]:                     cols_vals[sch["name"]] = name
        if sch["base_unit"]:                cols_vals[sch["base_unit"]] = unit_hint if unit_hint in BASE_FOR else "pcs"
        if sch["amount"]:                   cols_vals[sch["amount"]] = 0.0
        if sch["price_per_base"]:           cols_vals[sch["price_per_base"]] = 0.0
        if sch["type"]:                     cols_vals[sch["type"]] = "Other"
        if sch["stable"]:                   cols_vals[sch["stable"]] = 0
        # FIX: expiration is NOT NULL in your DB. Insert empty string, not NULL.
        if sch["expires"]:                  cols_vals[sch["expires"]] = ""
        if sch["token_cache"]:              cols_vals[sch["token_cache"]] = json.dumps({"alias": normalize_name(name)})
        if sch["total_cost"]:               cols_vals[sch["total_cost"]] = 0.0
        if sch["used_count"]:               cols_vals[sch["used_count"]] = 0

        cols = ", ".join(cols_vals.keys())
        ph   = ", ".join(["?"]*len(cols_vals))
        c.execute(f"INSERT INTO {sch['table']}({cols}) VALUES ({ph})", tuple(cols_vals.values()))
        iid = int(c.lastrowid)
        conn.commit(); conn.close()
        return iid, (cols_vals.get(sch["base_unit"]) or unit_hint or "pcs")
    except Exception:
        # fallback minimal insert
        try:
            if sch["user_id"] and sch["name"]:
                c.execute(f"INSERT INTO {sch['table']}({sch['user_id']},{sch['name']}) VALUES (?,?)", (user_id, name))
                iid = int(c.lastrowid)
                conn.commit(); conn.close()
                return iid, (unit_hint or "pcs")
        finally:
            conn.close()
        raise

# ----------------------------- Unit conversion --------------------------------

def to_base(amount: float, unit: str) -> Tuple[float, str]:
    unit = (unit or "pcs").lower()
    base = BASE_FOR.get(unit, unit)
    mult = MULTIPLIER_TO_BASE.get(unit, 1.0)
    return amount * mult, base

# ----------------------------- Data access ------------------------------------

def get_recipes(user_id: int):
    conn = get_connection(); c = conn.cursor()
    c.execute(
        """
        SELECT id, title, COALESCE(default_servings,2), COALESCE(time_min,20), COALESCE(difficulty,'Easy'),
               COALESCE(tags,''), COALESCE(cuisine,''), COALESCE(diet,''), COALESCE(allergens,''),
               COALESCE(photo,''), COALESCE(rating,0), COALESCE(favorite,0), COALESCE(course,'Dinner')
        FROM recipes_catalog WHERE user_id=? ORDER BY id DESC
        """, (user_id,))
    rows = c.fetchall(); conn.close()
    return rows

def get_recipe_meta(recipe_id:int):
    conn = get_connection(); c = conn.cursor()
    c.execute(
        """
        SELECT title, COALESCE(default_servings,2), COALESCE(time_min,20), COALESCE(difficulty,'Easy'),
               COALESCE(course,'Dinner'), COALESCE(cuisine,''), COALESCE(diet,''), COALESCE(allergens,''),
               COALESCE(tags,''), COALESCE(kcal_per_serv,0), COALESCE(protein_g,0), COALESCE(carbs_g,0),
               COALESCE(fat_g,0), COALESCE(rating,0), COALESCE(favorite,0), COALESCE(notes,''), COALESCE(photo,'')
        FROM recipes_catalog WHERE id=?
        """, (recipe_id,))
    row = c.fetchone(); conn.close()
    return row

def _recipe_user_id(recipe_id:int) -> Optional[int]:
    conn=get_connection(); c=conn.cursor()
    c.execute("SELECT user_id FROM recipes_catalog WHERE id=?", (recipe_id,))
    row=c.fetchone(); conn.close()
    return int(row[0]) if row else None

def _inv_fields_for_component(item_id: Optional[int]) -> Tuple[str,str,float,float,str,float]:
    if not item_id:
        return ("", "pcs", 0.0, 0.0, "Other", 0.0)
    info = _read_inventory_row(int(item_id))
    name = info.get("name","") or ""
    bu   = info.get("base_unit","pcs") or "pcs"
    amt  = float(info.get("amount",0.0) or 0.0)
    ppb  = float(info.get("price_per_base",0.0) or 0.0)
    typ  = info.get("type","Other") or "Other"
    tcost= float(info.get("total_cost",0.0) or 0.0)
    return (name, bu, amt, ppb, typ, tcost)

def get_recipe_components(recipe_id:int):
    conn=get_connection(); c=conn.cursor()
    c.execute(
        """
        SELECT id, ingredient_item_id,
               COALESCE(quantity_base,0), COALESCE(is_staple,0), COALESCE(is_optional,0),
               COALESCE(yield_pct,100), COALESCE(wastage_pct,0),
               COALESCE(category,''), COALESCE(vendor_sku,''), COALESCE(substitutions,''), COALESCE(note,'')
        FROM recipes_catalog_components
        WHERE recipe_id=?
        ORDER BY id
        """, (recipe_id,))
    rows_raw = c.fetchall()
    conn.close()

    rows=[]
    for (cid, ing_id, qty_base_def, is_staple, is_opt, y, w, cat, sku, subs, note) in rows_raw:
        nm, bu, have, ppb, inv_type, total_cost = _inv_fields_for_component(ing_id)
        rows.append((
            cid, ing_id, nm, bu, have, ppb, inv_type,
            qty_base_def, is_staple, is_opt, y, w, cat, sku, subs, note, total_cost
        ))
    return rows

# ----------------------------- Nutrition helpers ------------------------------

_BUILTIN_NUTRITION_100 = {
    "all purpose flour":    (364, 10.3, 76.2, 1.0),
    "flour":                (364, 10.3, 76.2, 1.0),
    "sugar":                (387, 0.0, 100.0, 0.0),
    "granulated sugar":     (387, 0.0, 100.0, 0.0),
    "olive oil":            (884, 0.0, 0.0, 100.0),
    "vegetable oil":        (884, 0.0, 0.0, 100.0),
    "milk":                 (60,  3.2, 4.8, 3.3),
    "egg":                  (155, 13.0, 1.1, 11.0),
    "eggs":                 (155, 13.0, 1.1, 11.0),
    "baking powder":        (53,  0.0, 28.1, 0.0),
    "salt":                 (0,   0.0, 0.0, 0.0),
    "cocoa powder":         (228, 19.6, 57.9, 13.7),
    "chocolate":            (546, 4.9, 61.0, 31.3),
    "hazelnut":             (628, 15.0, 17.0, 61.0),
    "vanilla extract":      (288, 0.1, 12.7, 0.1),
    "butter":               (717, 0.9, 0.1, 81.1),
    "yogurt":               (61,  3.5, 4.7, 3.3),
}

def _density_guess_g_per_ml(name_norm: str) -> float:
    if "oil" in name_norm: return 0.91
    if "honey" in name_norm: return 1.42
    if "milk" in name_norm: return 1.03
    if "yogurt" in name_norm: return 1.03
    return 1.00

def _pcs_to_grams_guess(name_norm: str) -> float:
    if "egg" in name_norm: return 50.0
    if "garlic" in name_norm and "clove" in name_norm: return 3.0
    if "onion" in name_norm: return 110.0
    return 0.0

def _items_table_has_nutrition(conn) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='items' LIMIT 1")
    if not cur.fetchone(): return False
    cur.execute("PRAGMA table_info(items)")
    cols = {r[1] for r in cur.fetchall()}
    needed = {"kcal_per_100g","protein_per_100g","carbs_per_100g","fat_per_100g","name","user_id"}
    return needed.issubset(cols)

def _pull_db_nutrition_map(user_id: int) -> dict:
    try:
        conn = get_connection()
        cur = conn.cursor()
        if _items_table_has_nutrition(conn):
            cur.execute("""
              SELECT name, kcal_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g
              FROM items WHERE user_id=?
            """, (user_id,))
            rows = cur.fetchall()
            conn.close()
            out = {}
            for n,k,p,c,f in rows:
                if not n: continue
                out[normalize_name(n)] = (float(k or 0), float(p or 0), float(c or 0), float(f or 0))
            return out
        cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='inventory' LIMIT 1")
        if cur.fetchone():
            cur.execute("PRAGMA table_info(inventory)")
            cols = {r[1] for r in cur.fetchall()}
            if {"name","kcal_per_100g","protein_per_100g","carbs_per_100g","fat_per_100g","user_id"}.issubset(cols):
                cur.execute("""
                  SELECT name, kcal_per_100g, protein_per_100g, carbs_per_100g, fat_per_100g
                  FROM inventory WHERE user_id=?
                """, (user_id,))
                rows = cur.fetchall()
                conn.close()
                out = {}
                for n,k,p,c,f in rows:
                    if not n: continue
                    out[normalize_name(n)] = (float(k or 0), float(p or 0), float(c or 0), float(f or 0))
                return out
        conn.close()
    except Exception:
        pass
    return {}

def _lookup_per100(user_id: int, name: str) -> tuple:
    norm = normalize_name(name)
    db = _pull_db_nutrition_map(user_id)
    if norm in db: return db[norm]
    if db:
        best = None; best_s = 0.0
        for k,v in db.items():
            s = difflib.SequenceMatcher(a=k, b=norm).ratio()
            if s > best_s:
                best_s = s; best = v
        if best and best_s >= 0.88:
            return best
    if norm in _BUILTIN_NUTRITION_100: return _BUILTIN_NUTRITION_100[norm]
    for k,v in _BUILTIN_NUTRITION_100.items():
        if k in norm:
            return v
    return (0.0, 0.0, 0.0, 0.0)

def _qty_to_grams(name: str, unit: str, qty: float) -> float:
    n = normalize_name(name)
    u = (unit or "g").lower()
    if u == "g": return float(qty)
    if u == "kg": return float(qty) * 1000.0
    if u == "mg": return float(qty) * 0.001
    if u == "ml": return float(qty) * _density_guess_g_per_ml(n)
    if u in ("pc","pcs","piece","pieces"): return float(qty) * _pcs_to_grams_guess(n)
    return float(qty)

def _fill_missing_nutrition(user_id: int, draft: dict) -> dict:
    need = any(float(draft.get(k, 0) or 0) <= 0 for k in ("kcal_per_serv","protein_g","carbs_g","fat_g"))
    if not need:
        return draft

    kcal=prot=carb=fat=0.0
    for c in draft.get("components") or []:
        name = c.get("name") or ""
        qty  = float(c.get("quantity_per_serving") or 0.0)
        unit = (c.get("unit") or "g").lower()
        grams = max(0.0, _qty_to_grams(name, unit, qty))
        if grams <= 0: continue
        k100,p100,c100,f100 = _lookup_per100(user_id, name)
        if k100==p100==c100==f100==0.0:
            continue
        factor = grams / 100.0
        kcal += k100 * factor
        prot += p100 * factor
        carb += c100 * factor
        fat  += f100 * factor

    if kcal > 0: draft["kcal_per_serv"] = int(round(kcal))
    if prot > 0: draft["protein_g"] = round(prot, 1)
    if carb > 0: draft["carbs_g"]   = round(carb, 1)
    if fat  > 0: draft["fat_g"]     = round(fat, 1)
    return draft

# ----------------------------- Coverage / Cost --------------------------------

def _ppb_from_row(price_per_base: float, total_cost: float, have_base: float) -> float:
    ppb = float(price_per_base or 0.0)
    if ppb > 0: return ppb
    if float(total_cost or 0) > 0 and float(have_base or 0) > 0:
        return float(total_cost) / float(have_base)
    return 0.0

def _is_staple_name(name: str, staples_list: Optional[List[str]] = None) -> bool:
    staples = set(normalize_name(s) for s in (staples_list or DEFAULT_STAPLES))
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
    staples_list=DEFAULT_STAPLES

    for (_cid, ing_id, nm, bu, have_base, ppb, _inv_type,
         q_base_def, is_staple, is_opt, yield_pct, wastage_pct, cat, sku, subs_json, note, total_cost_row) in comps:

        needed_raw = float(q_base_def or 0.0) * scale
        needed_with_waste = needed_raw * (100.0 + float(wastage_pct or 0.0))/100.0
        effective_need = needed_with_waste / max(0.01, float(yield_pct or 100.0)/100.0)

        staple = (bool(is_staple) and _is_staple_name(nm or "", staples_list))

        have = float(have_base or 0.0)
        unit_price = _ppb_from_row(ppb, total_cost_row, have_base)
        alt_used = False

        if not staple and user_id is not None and have <= 1e-9:
            alt = link_inventory(user_id, nm, unit_hint=bu)
            if alt and int(alt[0]) != int(ing_id or 0):
                alt_info = _read_inventory_row(int(alt[0]))
                have_alt = float(alt_info.get("amount",0.0) or 0.0)
                ppb_alt  = float(alt_info.get("price_per_base",0.0) or 0.0)
                tc_alt   = float(alt_info.get("total_cost",0.0) or 0.0)
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

# ----------------------------- Cooking (deduct inventory) ---------------------

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
    ts, mk = _today_keys()

    sch = _inventory_schema()
    amt_col = sch["amount"]; unit_col = sch["base_unit"]; used_col = sch["used_count"]
    if not sch["table"] or not amt_col or not unit_col:
        return False, "Inventory table is missing required columns."

    def _work(conn, c):
        for (_cid, ing_id, nm, bu, _have, _ppb, _inv_type,
             q_base_def, is_staple, is_opt, yield_pct, wastage_pct, _cat, _sku, _subs, _note, _tc) in comps:

            staple = (bool(is_staple) and _is_staple_name(nm or ""))
            if staple: 
                continue
            if bool(is_opt) and not deduct_optional:
                continue

            needed_raw=float(q_base_def or 0.0)*scale
            need = (needed_raw * (100.0 + float(wastage_pct or 0.0))/100.0) / max(0.01, float(yield_pct or 100)/100.0)
            if need<=0: 
                continue

            c.execute(f"SELECT id, COALESCE({amt_col},0), COALESCE({unit_col}, 'pcs'), COALESCE({used_col},0) FROM {sch['table']} WHERE id=?", (ing_id,))
            r=c.fetchone()
            if not r: 
                raise RuntimeError(f"Missing inventory item: {nm}")
            cur_id, cur_amt, base_unit, used_count = int(r[0]), float(r[1] or 0.0), (r[2] or bu), int(r[3] or 0)

            if cur_amt + 1e-9 < need:
                alt = link_inventory(user_id, nm, unit_hint=bu)
                if alt and int(alt[0]) != cur_id:
                    c.execute(f"SELECT COALESCE({amt_col},0), COALESCE({unit_col}, 'pcs'), COALESCE({used_col},0) FROM {sch['table']} WHERE id=?", (int(alt[0]),))
                    rr=c.fetchone()
                    if rr and float(rr[0] or 0.0) >= need - 1e-9:
                        c.execute("UPDATE recipes_catalog_components SET ingredient_item_id=? WHERE id=?", (int(alt[0]), _cid))
                        cur_id, cur_amt, base_unit, used_count = int(alt[0]), float(rr[0] or 0.0), (rr[1] or bu), int(rr[2] or 0)

            new_amt = max(0.0, cur_amt - need)
            step = _safe_step_count(user_id, base_unit) + 1

            if used_col:
                c.execute(f"UPDATE {sch['table']} SET {amt_col}=?, {used_col}=? WHERE id=?", (new_amt, used_count + int(step), cur_id))
            else:
                c.execute(f"UPDATE {sch['table']} SET {amt_col}=? WHERE id=?", (new_amt, cur_id))

            c.execute(
                """
                INSERT INTO usage_log (user_id,item_id,event_type,quantity,unit,step_count,value_shekel,ts,month_key)
                VALUES (?, ?, 'used', ?, ?, ?, 0.0, ?, ?)
                """,
                (user_id, cur_id, float(need), base_unit, int(step), ts, mk))

    try:
        _txn_retry("BEGIN IMMEDIATE", _work, max_wait_ms=3000)
    except Exception as e:
        return False, f"Cook failed: {e}"
    return True, f"Cooked {title} for {servings} serving(s)."

# ----------------------------- Create / persist -------------------------------

def create_recipe_atomic(user_id:int, meta:dict, components:List[dict], steps:List[dict]) -> int:
    """
    Supports two component shapes from the UI builder:
      A) inventory-picked rows: {inv_id, qty_per_serv, staple, optional, yield_pct, wastage_pct, ...}
      B) manual rows:           {name, unit, qty_per_serv, ...}
    Ensures ingredient_item_id is always a valid inventory id and avoids nested writers.
    """
    staples=set(normalize_name(s) for s in _cached_staples_raw())

    # Pass 1: resolve or create inventory items OUTSIDE the main TX
    resolved: List[Tuple[int,float,int,int,float,float,str,str,str,str]] = []
    for comp in components:
        ing_id=None; bu=None

        if comp.get("inv_id"):  # chosen from inventory
            ing_id=int(comp["inv_id"])
            _, bu, *_ = _inv_fields_for_component(ing_id)
            if not bu: bu="pcs"
        else:                    # manual row → link or create with its own short write
            nm=(comp.get("name") or "").strip()
            unit=(comp.get("unit") or "pcs")
            guess=link_inventory(user_id, nm, unit_hint=unit)
            if guess:
                ing_id, bu = int(guess[0]), guess[1]
            else:
                ing_id, bu = _ensure_inventory_item(user_id, nm, unit_hint=unit)

        qty_ui=float(comp.get("qty_per_serv",0))*int(meta["default_servings"])
        need_base,_=to_base(qty_ui, bu)

        nm_for_staple = comp.get("name","") if "name" in comp else _inv_fields_for_component(ing_id)[0]
        is_staple = 1 if (comp.get("staple") and normalize_name(nm_for_staple) in staples) else 0

        resolved.append((
            int(ing_id), float(need_base), is_staple,
            1 if comp.get("optional") else 0,
            float(comp.get("yield_pct",100)),
            float(comp.get("wastage_pct",0)),
            comp.get("category","") or "",
            comp.get("vendor_sku","") or "",
            json.dumps(comp.get("subs",[]) or []),
            comp.get("note","") or ""
        ))

    rid_holder = {"rid": None}

    def _work(conn, c):
        c.execute(
            """
            INSERT INTO recipes_catalog(user_id,title,default_servings,time_min,difficulty,course,cuisine,diet,allergens,tags,
                         kcal_per_serv,protein_g,carbs_g,fat_g,notes,photo)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)
            """,
            (user_id, meta["title"].strip(), int(meta["default_servings"]), int(meta["time_min"]), meta["difficulty"],
             meta.get("course",""), meta.get("cuisine",""), meta.get("diet",""), meta.get("allergens",""),
             meta.get("tags",""), float(meta.get("kcal",0)), float(meta.get("protein",0)),
             float(meta.get("carbs",0)), float(meta.get("fat",0)), meta.get("notes",""))
        )
        rid=int(c.lastrowid)
        rid_holder["rid"] = rid

        for (ing_id, need_base, is_staple, is_opt, y, w, cat, sku, subs_j, note) in resolved:
            c.execute(
                """
                INSERT INTO recipes_catalog_components
                (recipe_id,ingredient_item_id,quantity_base,is_staple,is_optional,yield_pct,wastage_pct,category,vendor_sku,substitutions,note)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (rid, ing_id, need_base, is_staple, is_opt, y, w, cat, sku, subs_j, note)
            )

        for i, step in enumerate(steps, start=1):
            equip = step.get("equipment",[]) or []
            c.execute(
                """
                INSERT INTO recipe_steps(recipe_id,position,text,minutes,equipment,photo)
                VALUES (?,?,?,?,?,?)
                """,
                (rid, i, (step.get("text","") or "").strip(),
                 int(step.get("minutes",0)),
                 ",".join(equip),
                 step.get("photo","") or "")
            )

    _txn_retry("BEGIN IMMEDIATE", _work, max_wait_ms=3000)
    return int(rid_holder["rid"])

def persist_ai_recipe(user_id:int, draft:dict) -> int:
    meta = {
        "title": draft.get("title","New AI Recipe"),
        "default_servings": int(draft.get("default_servings",2)),
        "time_min": int(draft.get("time_min",20)),
        "difficulty": draft.get("difficulty","Easy"),
        "course": draft.get("course","Dinner"),
        "cuisine": draft.get("cuisine",""),
        "diet": draft.get("diet",""),
        "allergens": ",".join(draft.get("allergens") or []),
        "tags": ",".join(draft.get("tags") or []),
        "kcal": float(draft.get("kcal_per_serv",0)),
        "protein": float(draft.get("protein_g",0)),
        "carbs": float(draft.get("carbs_g",0)),
        "fat": float(draft.get("fat_g",0)),
        "notes": draft.get("notes","")
    }
    comps=[]
    for c in draft.get("components") or []:
        comps.append({
            "name": c.get("name","").strip(),
            "unit": (c.get("unit") or "g"),
            "qty_per_serv": float(c.get("quantity_per_serving",0.0)),
            "staple": bool(c.get("staple", False)),
            "optional": bool(c.get("optional", False)),
            "yield_pct": float(c.get("yield_pct",100.0)),
            "wastage_pct": float(c.get("wastage_pct",0.0)),
            "category": "",
            "vendor_sku": "",
            "subs": [],
            "note": ""
        })
    steps=[]
    for s in draft.get("steps") or []:
        steps.append({
            "text": s.get("text",""),
            "minutes": int(s.get("minutes",0)),
            "equipment": s.get("equipment",[]) or [],
            "photo": s.get("photo","")
        })
    return create_recipe_atomic(user_id, meta, comps, steps)

# ----------------------------- AI generator -----------------------------------

def ai_generate_recipe(user_id:int, constraints:str)->Optional[dict]:
    """
    Real prompt-following generator:
    - Uses OPENAI_API_KEY if set to call an LLM and return strict JSON.
    - If unavailable, uses an olive-oil cake or pantry-based fallback.
    """
    txt = (constraints or "").strip()
    norm = normalize_name(txt)

    def _default_unit_for(name: str) -> str:
        n = normalize_name(name)
        if any(k in n for k in ["oil","water","milk","juice","extract","vanilla"]): return "ml"
        if "egg" in n: return "pcs"
        return "g"

    def _resolved_unit(name: str, hint: Optional[str] = None) -> str:
        u_hint = (hint or _default_unit_for(name))
        guess = link_inventory(user_id, name, unit_hint=u_hint)
        return guess[1] if guess else u_hint

    def _add_comp(components: list, name: str, qty: float, unit: Optional[str] = None,
                  staple: bool = False, optional: bool = False, y: float = 100.0, w: float = 0.0):
        components.append({
            "name": name, "unit": _resolved_unit(name, unit),
            "quantity_per_serving": float(qty),
            "staple": bool(staple), "optional": bool(optional),
            "yield_pct": float(y), "wastage_pct": float(w),
        })

    def _olive_oil_cake_template() -> dict:
        comps: List[dict] = []
        _add_comp(comps, "all-purpose flour", 70, "g")
        _add_comp(comps, "sugar", 40, "g", staple=True)
        _add_comp(comps, "olive oil", 30, "ml", staple=True)
        _add_comp(comps, "egg", 0.5, "pcs")
        _add_comp(comps, "milk", 40, "ml", optional=True)
        _add_comp(comps, "baking powder", 3, "g", staple=True)
        _add_comp(comps, "salt", 1, "g", staple=True, optional=True)
        steps = [
            {"text": "Heat oven to 175°C. Grease a small pan.", "minutes": 5, "equipment": ["oven","pan"]},
            {"text": "Whisk oil, egg, milk. Separately mix flour, sugar, baking powder, salt.", "minutes": 5, "equipment": ["bowl","whisk"]},
            {"text": "Combine, pour, bake until a skewer is clean.", "minutes": 25, "equipment": ["oven"]},
        ]
        r = {
            "title": "Olive Oil Cake",
            "default_servings": 2, "time_min": 35, "difficulty": "Easy",
            "course": "Dessert", "cuisine": "", "diet": "",
            "tags": ["Auto"], "allergens": [],
            "kcal_per_serv": 450, "protein_g": 7, "carbs_g": 50, "fat_g": 22,
            "steps": steps, "components": comps
        }
        return _fill_missing_nutrition(user_id, r)

    def _inventory_fallback() -> dict:
        inv = _cached_inventory_raw(user_id)
        picks = [r for r in inv if (r[3] or 0) > 0]
        random.shuffle(picks)
        picks = picks[:min(8, max(3, len(picks)//2 or 3))]
        title = f"{random.choice(['Quick','Rustic','Weeknight','Comfort'])} " + (picks[0][1] if picks else "Pantry Dish")
        comps = []
        for pid, name, bu, amt, *_ in picks:
            per = 150.0 if (bu or "pcs") in ("g","ml") else 1.0
            comps.append({"name":name,"unit":bu or "pcs","quantity_per_serving":per,"staple":False,"optional":False,"yield_pct":100.0,"wastage_pct":0.0})
        steps=[{"text":"Prep ingredients.","minutes":5,"equipment":["knife","board"]},
               {"text":"Cook until done.","minutes":15,"equipment":["pan"]}]
        r = {"title":title,"default_servings":2,"time_min":20,"difficulty":"Easy","course":"Dinner",
             "cuisine":"","diet":"","tags":["Auto"],"allergens":[],
             "kcal_per_serv":450,"protein_g":25,"carbs_g":40,"fat_g":18,
             "steps":steps,"components":comps}
        return _fill_missing_nutrition(user_id, r)

    api_key = os.getenv("OPENAI_API_KEY")
    model_name = os.getenv("RECIPE_AI_MODEL") or "gpt-4o-mini"

    if api_key:
        inv = _cached_inventory_raw(user_id)
        inv_units = {normalize_name(nm): bu for (_id, nm, bu, *_rest) in inv if nm and bu}

        system = (
            "You are a professional recipe developer. Return ONLY compact JSON that matches the schema. "
            "Units must be one of ['g','ml','pcs']. Prefer these units when applicable: " + json.dumps(inv_units) + ". "
            "Do not add irrelevant ingredients. Respect the prompt."
        )
        schema_hint = {
            "title": "string", "default_servings": 2, "time_min": 30, "difficulty": "Easy",
            "course": "Dinner", "cuisine": "", "diet": "", "tags": ["Auto"], "allergens": [],
            "kcal_per_serv": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0,
            "components": [{"name":"string","unit":"g|ml|pcs","quantity_per_serving":0.0,"staple":False,"optional":False,"yield_pct":100.0,"wastage_pct":0.0}],
            "steps": [{"text":"string","minutes":5,"equipment":["bowl"]}]
        }
        user_msg = ("Request: " + txt + "\n"
                    "Respond ONLY with minified JSON using this schema (field names exact): " + json.dumps(schema_hint))

        def _call_openai_v1()->Optional[dict]:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=api_key)
                resp = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role":"system","content":system},{"role":"user","content":user_msg}],
                    temperature=0.4, response_format={"type":"json_object"},
                )
                return json.loads(resp.choices[0].message.content)
            except Exception:
                return None

        def _call_openai_legacy()->Optional[dict]:
            try:
                import openai as _oai
                _oai.api_key = api_key
                resp = _oai.ChatCompletion.create(
                    model=model_name,
                    messages=[{"role":"system","content":system},{"role":"user","content":user_msg}],
                    temperature=0.4,
                )
                return json.loads(resp["choices"][0]["message"]["content"])
            except Exception:
                return None

        data = _call_openai_v1() or _call_openai_legacy()
        if isinstance(data, dict) and data.get("components") and data.get("steps"):
            comps=[]
            for c in data.get("components") or []:
                nm=(c.get("name") or "").strip()
                if not nm: continue
                unit=(c.get("unit") or _default_unit_for(nm)).lower()
                if unit not in ("g","ml","pcs"): unit=_default_unit_for(nm)
                qty=float(c.get("quantity_per_serving") or 0.0)
                if qty<=0: continue
                comps.append({
                    "name": nm, "unit": _resolved_unit(nm, unit),
                    "quantity_per_serving": qty,
                    "staple": bool(c.get("staple", False)),
                    "optional": bool(c.get("optional", False)),
                    "yield_pct": float(c.get("yield_pct", 100.0)),
                    "wastage_pct": float(c.get("wastage_pct", 0.0)),
                })
            steps=[]
            for s in data.get("steps") or []:
                t=(s.get("text") or "").strip()
                if not t: continue
                steps.append({"text": t, "minutes": int(s.get("minutes", 0)), "equipment": s.get("equipment", []) or []})
            if comps and steps:
                result = {
                    "title": data.get("title", "New AI Recipe"),
                    "default_servings": int(data.get("default_servings", 2)),
                    "time_min": int(data.get("time_min", 20)),
                    "difficulty": data.get("difficulty", "Easy"),
                    "course": data.get("course", "Dinner"),
                    "cuisine": data.get("cuisine", ""), "diet": data.get("diet", ""),
                    "tags": data.get("tags", ["Auto"]) or ["Auto"],
                    "allergens": data.get("allergens", []) or [],
                    "kcal_per_serv": float(data.get("kcal_per_serv", 0)),
                    "protein_g": float(data.get("protein_g", 0)),
                    "carbs_g": float(data.get("carbs_g", 0)),
                    "fat_g": float(data.get("fat_g", 0)),
                    "steps": steps, "components": comps,
                }
                return _fill_missing_nutrition(user_id, result)

    if ("cake" in norm) and ("olive" in norm and "oil" in norm):
        return _olive_oil_cake_template()

    return _inventory_fallback()

# ----------------------------- Maintenance ------------------------------------

def set_component_staple(component_id:int, is_staple:bool) -> None:
    conn=get_connection(); c=conn.cursor()
    c.execute("UPDATE recipes_catalog_components SET is_staple=? WHERE id=?", (1 if is_staple else 0, int(component_id)))
    conn.commit(); conn.close()

def reset_staples_for_recipe(recipe_id:int) -> int:
    safe = set(normalize_name(s) for s in SAFE_DEFAULT_STAPLES)
    conn=get_connection(); c=conn.cursor()
    c.execute(
        """
        SELECT rcc.id, i.name
        FROM recipes_catalog_components rcc
        JOIN inventory i ON i.id=rcc.ingredient_item_id
        WHERE rcc.recipe_id=?
        """, (recipe_id,))
    rows=c.fetchall(); touched=0
    for cid, nm in rows:
        new_val = 1 if normalize_name(nm) in safe else 0
        c.execute("UPDATE recipes_catalog_components SET is_staple=? WHERE id=?", (new_val, cid))
        touched += 1
    conn.commit(); conn.close()
    return touched

def recompute_staples_for_recipe(recipe_id:int) -> int:
    return reset_staples_for_recipe(recipe_id)

def reset_all_staples_to_defaults(user_id:int) -> int:
    safe = set(normalize_name(s) for s in SAFE_DEFAULT_STAPLES)
    conn=get_connection(); c=conn.cursor()
    c.execute(
        """
        SELECT rcc.id, i.name
        FROM recipes_catalog_components rcc
        JOIN recipes_catalog r ON r.id=rcc.recipe_id
        JOIN inventory i ON i.id=rcc.ingredient_item_id
        WHERE r.user_id=?
        """, (user_id,))
    rows=c.fetchall(); touched=0
    for cid, nm in rows:
        new_val = 1 if normalize_name(nm) in safe else 0
        c.execute("UPDATE recipes_catalog_components SET is_staple=? WHERE id=?", (new_val, cid))
        touched += 1
    conn.commit(); conn.close()
    return touched

def repair_links_for_recipe(recipe_id:int) -> int:
    user_id = _recipe_user_id(recipe_id)
    if user_id is None:
        return 0
    comps = get_recipe_components(recipe_id)
    changed = 0

    def _work(conn, c):
        nonlocal changed
        for (_cid, ing_id, nm, bu, have, _ppb, _inv_type,
             _q, is_staple, _is_opt, _y, _w, _cat, _sku, _subs, _note, _tc) in comps:
            guess = link_inventory(user_id, nm, unit_hint=bu)
            if not guess: 
                continue
            new_id = int(guess[0])
            if new_id != int(ing_id or 0):
                alt_info = _read_inventory_row(new_id)
                if float(alt_info.get("amount",0.0) or 0.0) > float(have or 0.0):
                    c.execute("UPDATE recipes_catalog_components SET ingredient_item_id=? WHERE id=?", (new_id, _cid))
                    changed += 1

    _txn_retry("BEGIN IMMEDIATE", _work, max_wait_ms=3000)
    return changed

def diagnose_recipe_links(recipe_id:int) -> List[Dict]:
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

# ----------------------------- Delete recipe ----------------------------------

def delete_recipe(user_id: int, recipe_id: int) -> bool:
    """Hard-delete a recipe and its children (components + steps)."""
    def _work(conn, cur):
        cur.execute("SELECT 1 FROM recipes_catalog WHERE id=? AND user_id=?", (recipe_id, user_id))
        if not cur.fetchone():
            raise RuntimeError("Recipe not found or not owned by user")
        cur.execute("DELETE FROM recipe_steps WHERE recipe_id=?", (recipe_id,))
        cur.execute("DELETE FROM recipes_catalog_components WHERE recipe_id=?", (recipe_id,))
        cur.execute("DELETE FROM recipes_catalog WHERE id=? AND user_id=?", (recipe_id, user_id))
    try:
        _txn_retry("BEGIN IMMEDIATE", _work, max_wait_ms=3000)
        return True
    except Exception:
        return False

# ----------------------------- Misc -------------------------------------------

def ensure_schema():
    # Placeholder for UI expectation. No-op here.
    return
