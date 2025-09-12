# RecipesPage.py
# Streamlit UI for the Recipes feature built on recipes_core.py

from __future__ import annotations
import math
from datetime import date
from typing import List, Dict

import streamlit as st
import recipes_core as rc

# ----------------------------- Styling ----------------------------------------

PALETTE = {
    "bg": "#0E1117", "surface": "#151A23", "card": "#1B2230",
    "text": "#EAF0FF", "muted": "#9FB0CC", "brand": "#7C5CFC",
    "ok": "#34D399", "warn": "#FBBF24", "err": "#F87171", "ring": "#2B3245", "chip": "#243145"
}

def inject_theme():
    st.markdown(f"""
    <style>
      html, body, [data-testid="stAppViewContainer"] {{ background:{PALETTE['bg']} !important; }}
      .rcard {{
        background: linear-gradient(180deg, rgba(255,255,255,.02), rgba(0,0,0,.09));
        border: 1px solid rgba(255,255,255,.06);
        border-radius: 16px; padding: 14px; margin-bottom: 10px;
        box-shadow: 0 8px 20px rgba(0,0,0,.25);
      }}
      .thumb {{
        width: 100%; height: 140px; border-radius: 12px;
        background: linear-gradient(90deg,#182033 25%,#21293e 50%,#182033 75%);
      }}
      .h1 {{ font-weight: 600; color: {PALETTE['text']}; font-size: 18px; margin: 8px 0 2px; }}
      .muted {{ color: {PALETTE['muted']}; font-size: 13px; }}
      .chip {{ display:inline-block; padding:2px 8px; border-radius:999px; font-size:12px; background:{PALETTE['chip']}; color:#d1e3ff; margin-right:6px; border:1px solid rgba(255,255,255,.08); }}
      .chip.ok {{ background:rgba(52,211,153,.12); color:#a9f0d2; border-color: rgba(52,211,153,.32); }}
      .chip.warn {{ background:rgba(251,191,36,.12); color:#ffe1a3; border-color: rgba(251,191,36,.35); }}
      .chip.err {{ background:rgba(248,113,113,.12); color:#ffc0c0; border-color: rgba(248,113,113,.35); }}
      .bar {{height:10px; background:#223046; border-radius:999px; overflow:hidden}}
      .bar>div {{height:100%}}
      .smallbtn button {{ padding-top: 0.25rem !important; padding-bottom: 0.25rem !important; }}
      .note {{ color:#a3baff; font-size:12px; opacity:.85 }}
      .tcell {{ padding:6px 8px; border-bottom:1px solid rgba(255,255,255,.06); }}
    </style>
    """, unsafe_allow_html=True)

# ----------------------------- Cache wrappers ---------------------------------

@st.cache_data(show_spinner=False, ttl=20)
def cached_staples() -> List[str]:
    return rc._cached_staples_raw()

@st.cache_data(show_spinner=False, ttl=10)
def cached_inventory(user_id: int):
    return rc._cached_inventory_raw(user_id)

def _invalidate_cache():
    cached_inventory.clear()
    cached_staples.clear()

rc.cached_inventory = cached_inventory
rc.cached_staples = cached_staples
rc.invalidate_cache = _invalidate_cache

# ----------------------------- Tiny UI helpers --------------------------------

def ring(percent:int, size:int=64, stroke:int=8, kind:str="ok"):
    pct=max(0,min(100,int(percent))); r=(size-stroke)/2; circ=2*math.pi*r
    dash=circ*pct/100; gap=circ-dash
    color={"ok":PALETTE["ok"],"warn":PALETTE["warn"],"err":PALETTE["err"]}.get(kind,PALETTE["ok"])
    svg=f"""<div><svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">
      <circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{PALETTE['ring']}" stroke-width="{stroke}" />
      <circle cx="{size/2}" cy="{size/2}" r="{r}" fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round"
              stroke-dasharray="{dash} {gap}" transform="rotate(-90 {size/2} {size/2})"/>
      <text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle"
            fill="{PALETTE['text']}" font-family="Inter" font-size="13">{pct}%</text>
    </svg></div>"""
    st.markdown(svg, unsafe_allow_html=True)

def bar(pct:int):
    color=PALETTE["ok"] if pct==100 else (PALETTE["warn"] if pct>=60 else PALETTE["err"])
    st.markdown(f'<div class="bar"><div style="width:{pct}%; background:{color}"></div></div>', unsafe_allow_html=True)

def chips(texts:List[str], color_class:str=""):
    for t in texts:
        if t.strip():
            st.markdown(f"<span class='chip {color_class}'>{t.strip()}</span>", unsafe_allow_html=True)

# ----------------------------- Cards / rows -----------------------------------

def recipe_card_row(r:tuple, cov:Dict):
    rid, title, dsv, tmin, diff, tags, cuisine, diet, allergens, photo, rating, fav, course = r
    with st.container():
        st.markdown("<div class='rcard'>", unsafe_allow_html=True)
        st.markdown(f"<div class='thumb'></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='h1'>{title}</div>", unsafe_allow_html=True)
        st.markdown(f"<div class='muted'>{course or 'Meal'} • {tmin} min • {diff}</div>", unsafe_allow_html=True)
        chips((tags or "").split(","))
        co1, co2 = st.columns([1,2])
        with co1: ring(cov["coverage_pct"], 68, 8, cov["status"])
        with co2:
            label = "✓ Can cook" if cov["status"]=="ok" else ("▲ Partial" if cov["status"]=="warn" else "■ Missing")
            st.markdown(f"<span class='chip {cov['status']}'>{label}</span>", unsafe_allow_html=True)
            b1,b2,b3,b4 = st.columns(4)
            if b1.button("View", key=f"v{rid}"):
                st.session_state["recipe_view_id"]=rid; st.rerun()
            if b2.button("Cook", disabled=cov["status"]=="err", key=f"ck{rid}"):
                st.session_state["recipe_view_id"]=rid; st.session_state["recipe_cook_now"]=True; st.rerun()
            if b3.button("Fav ★" if not fav else "Unfav ☆", key=f"fv{rid}"):
                conn=rc.get_connection()
                conn.execute("UPDATE recipes_catalog SET favorite=? WHERE id=?", (0 if fav else 1, rid))
                conn.commit(); conn.close()
                st.rerun()
            if b4.button("Book ➕", key=f"bk{rid}"):
                st.info("Books UI placeholder.")

# ----------------------------- Library tab ------------------------------------

def tab_library(user_id:int):
    st.subheader("Library")
    qc1, qc2, qc3, qc4 = st.columns([2,1,1,1])
    q = qc1.text_input("Search by title/tag/cuisine")
    course = qc2.selectbox("Course", ["All","Breakfast","Lunch","Dinner","Dessert","Snack","Drink"])
    favonly = qc3.checkbox("Favorites only", value=False)
    ready = qc4.selectbox("Cookability", ["Any","Can cook","Partial","Missing"])

    rows = rc.get_recipes(user_id)
    out=[]
    for r in rows:
        rid, title, dsv, tmin, diff, tags, cuisine, diet, allergens, photo, rating, fav, course_val = r
        if q:
            t=q.lower()
            if t not in (title or "").lower() and t not in (tags or "").lower() and t not in (cuisine or "").lower():
                continue
        if course!="All" and (course_val or "") != course:
            continue
        cov = rc.coverage_for_recipe(rid, dsv or 2)
        if ready=="Can cook" and cov["status"]!="ok": continue
        if ready=="Partial" and cov["status"]!="warn": continue
        if ready=="Missing" and cov["status"]!="err": continue
        out.append((r, cov))

    if not out:
        st.info("No recipes match.")
    else:
        cols = st.columns(2)
        for i,(r,cov) in enumerate(out[:50]):
            with cols[i%2]: recipe_card_row(r, cov)

    rid = st.session_state.get("recipe_view_id")
    if rid: _detail_ui(user_id, rid)

# ----------------------------- Create tab (manual) ----------------------------

def _builder_key(): return "builder_rows_v6"
def _steps_key(): return "builder_steps_v6"

def _ensure_builder():
    st.session_state.setdefault(_builder_key(), [])
    st.session_state.setdefault(_steps_key(), [])

def _add_row(default_mode="inventory"):
    st.session_state[_builder_key()].append({
        "mode": default_mode, "inv_id": None, "name":"", "unit":"g",
        "qty_per_serv": 0.0, "staple": False, "optional": False,
        "yield_pct": 100.0, "wastage_pct": 0.0, "category":"", "vendor_sku":"",
        "subs": [], "note":""
    })

def _add_step():
    st.session_state[_steps_key()].append({"text":"", "minutes":0, "equipment":[], "photo":""})

def _swap(lst, i, j):
    if 0<=i<len(lst) and 0<=j<len(lst):
        lst[i], lst[j] = lst[j], lst[i]

def tab_create(user_id:int):
    st.subheader("Create recipe")
    _ensure_builder()
    inv = cached_inventory(user_id)
    inv_map = {r[0]: r for r in inv}

    with st.form("builder_form", clear_on_submit=False):
        # META
        m1, m2, m3 = st.columns([2,1,1])
        title = m1.text_input("Title", "")
        dsv   = m2.number_input("Default servings", min_value=1, value=2, step=1)
        tmin  = m3.number_input("Time (min)", min_value=1, value=20, step=5)
        m4, m5, m6 = st.columns([1,1,2])
        diff  = m4.selectbox("Difficulty", ["Easy","Medium","Hard"])
        course= m5.selectbox("Course", ["Dinner","Lunch","Breakfast","Dessert","Snack","Drink"])
        cuisine = m6.text_input("Cuisine")
        m7, m8 = st.columns([2,1])
        tags = m7.text_input("Tags (comma)")
        diet = m8.text_input("Diet")
        allergens = st.multiselect("Allergens", ["gluten","dairy","nuts","soy","egg","fish","shellfish","sesame","vegan","vegetarian","halal","kosher"])
        n1, n2, n3, n4 = st.columns(4)
        kcal = n1.number_input("kcal / serving", min_value=0.0, step=10.0, value=0.0)
        prot = n2.number_input("Protein g / serving", min_value=0.0, step=1.0, value=0.0)
        carbs= n3.number_input("Carbs g / serving", min_value=0.0, step=1.0, value=0.0)
        fat  = n4.number_input("Fat g / serving", min_value=0.0, step=1.0, value=0.0)
        notes= st.text_area("Notes / description")

        st.markdown("#### Ingredients")
        rows = st.session_state[_builder_key()]
        if not rows: _add_row("inventory")

        for idx, row in enumerate(rows):
            m1,m2,m3,m4,m5,m6,m7,m8,m9,m10,m11,m12,m13 = st.columns([0.9,3.0,1.1,0.9,0.8,0.9,1.0,1.0,1.2,1.2,1.8,0.6,1.7])

            row["mode"] = m1.selectbox("Mode", ["inventory","manual"], index=0 if row["mode"]!="manual" else 1, key=f"bm{idx}")

            if row["mode"]=="inventory":
                choice = m2.selectbox(
                    "Ingredient",
                    [("",None)] + [(f"{r[1]} [{r[2]}] • on {float(r[3] or 0):.1f}", r[0]) for r in inv],
                    format_func=lambda x: x[0] if isinstance(x,tuple) else x, key=f"bi{idx}")
                row["inv_id"]= choice[1] if isinstance(choice,tuple) else None
                bu = inv_map.get(row["inv_id"], (None,None,"pcs"))[2] if row.get("inv_id") else "pcs"
                row["qty_per_serv"] = m3.number_input("Qty/serv", min_value=0.0, step=1.0, value=float(row.get("qty_per_serv") or 0.0), key=f"bq{idx}")
                m4.write(f"**{bu}**"); row["unit"]=bu
                m13.write("—")
            else:
                row["name"] = m2.text_input("Name", value=row.get("name",""), key=f"bn{idx}")
                row["qty_per_serv"] = m3.number_input("Qty/serv", min_value=0.0, step=1.0, value=float(row.get("qty_per_serv") or 0.0), key=f"bq{idx}")
                row["unit"] = m4.selectbox("Unit", rc.UNITS, index=rc.UNITS.index(row.get("unit","g")), key=f"bu{idx}")
                row["inv_id"]=None
                link = rc.link_inventory(user_id, row.get("name",""), unit_hint=row.get("unit","pcs")) if row.get("name") else None
                if link:
                    iid, buh = link; invrow = inv_map.get(iid)
                    label = f"→ {invrow[1]} [{buh}] • on {float(invrow[3] or 0):.1f}"
                    m13.markdown(f"<span class='chip ok'>{label}</span>", unsafe_allow_html=True)
                else:
                    m13.markdown(f"<span class='chip warn'>no link</span>", unsafe_allow_html=True)

            row["staple"]  = m5.checkbox("Staple", value=bool(row.get("staple",False)), key=f"bs{idx}")
            row["optional"]= m6.checkbox("Optional", value=bool(row.get("optional",False)), key=f"bo{idx}")
            row["yield_pct"]= m7.number_input("Yield%", min_value=1.0, max_value=100.0, step=1.0, value=float(row.get("yield_pct",100)), key=f"by{idx}")
            row["wastage_pct"]=m8.number_input("Waste%", min_value=0.0, max_value=90.0, step=1.0, value=float(row.get("wastage_pct",0)), key=f"bw{idx}")
            row["category"]= m9.text_input("Category", value=row.get("category",""), key=f"bc{idx}")
            row["vendor_sku"]= m10.text_input("SKU", value=row.get("vendor_sku",""), key=f"bsku{idx}")
            row["note"]= m11.text_input("Note", value=row.get("note",""), key=f"bt{idx}")

            if m12.form_submit_button("✕", key=f"bd{idx}"):
                del rows[idx]; st.rerun()

        cA, cB = st.columns([1,3])
        if cA.form_submit_button("Add ingredient row ➕", key="builder_add_row"):
            _add_row("inventory"); st.rerun()

        st.markdown("#### Steps")
        steps = st.session_state[_steps_key()]
        if not steps: _add_step()
        for i, step in enumerate(steps):
            s1,s2,s3,s4,s5,s6 = st.columns([0.5,4.0,1.0,2.0,0.6,0.6])
            s1.write(str(i+1))
            step["text"] = s2.text_input("Text", value=step.get("text",""), key=f"st{i}")
            step["minutes"] = s3.number_input("Min", min_value=0, value=int(step.get("minutes",0)), key=f"sm{i}")
            eq_txt = s4.text_input("Equipment (comma)", value=",".join(step.get("equipment",[])), key=f"se{i}")
            step["equipment"] = [x.strip() for x in eq_txt.split(",") if x.strip()]
            if s5.form_submit_button("↑", key=f"su{i}"): _swap(steps,i,max(i-1,0)); st.rerun()
            if s6.form_submit_button("↓", key=f"sd{i}"): _swap(steps,i,min(i+1,len(steps)-1)); st.rerun()
        if st.form_submit_button("Add step ➕", key="builder_add_step"):
            _add_step(); st.rerun()

        submit = st.form_submit_button("Save recipe", key="builder_save_recipe")
        if submit:
            if not title.strip():
                st.error("Title is required")
                return
            comps=[]
            for r in rows:
                if r["mode"]=="inventory" and r.get("inv_id") and float(r.get("qty_per_serv") or 0)>0:
                    comps.append({
                        "inv_id": int(r["inv_id"]),
                        "qty_per_serv": float(r["qty_per_serv"]),
                        "staple": bool(r.get("staple")),
                        "optional": bool(r.get("optional")),
                        "yield_pct": float(r.get("yield_pct",100)),
                        "wastage_pct": float(r.get("wastage_pct",0)),
                        "category": r.get("category",""),
                        "vendor_sku": r.get("vendor_sku",""),
                        "subs": r.get("subs",[]),
                        "note": r.get("note","")
                    })
                elif r["mode"]=="manual" and r.get("name") and float(r.get("qty_per_serv") or 0)>0:
                    comps.append({
                        "name": r["name"].strip(),
                        "unit": r.get("unit","pcs"),
                        "qty_per_serv": float(r["qty_per_serv"]),
                        "staple": bool(r.get("staple")),
                        "optional": bool(r.get("optional")),
                        "yield_pct": float(r.get("yield_pct",100)),
                        "wastage_pct": float(r.get("wastage_pct",0)),
                        "category": r.get("category",""),
                        "vendor_sku": r.get("vendor_sku",""),
                        "subs": r.get("subs",[]),
                        "note": r.get("note","")
                    })
            if not comps:
                st.error("Add at least one ingredient.")
                return

            meta = {
                "title": title, "default_servings": int(dsv), "time_min": int(tmin),
                "difficulty": diff, "course": course, "cuisine": cuisine, "diet": diet,
                "allergens": ",".join(allergens), "tags": tags, "kcal": float(kcal),
                "protein": float(prot), "carbs": float(carbs), "fat": float(fat),
                "notes": notes
            }
            try:
                rid=rc.create_recipe_atomic(user_id, meta, comps, st.session_state[_steps_key()])
                st.success("Recipe saved.")
                st.session_state[_builder_key()] = []; st.session_state[_steps_key()] = []
                st.session_state["recipe_view_id"]=rid
                _invalidate_cache()
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")

# ----------------------------- AI Create tab ----------------------------------

def _ai_key(): return "ai_draft_v1"

def _ensure_ai_draft():
    st.session_state.setdefault(_ai_key(), None)
    st.session_state.setdefault("ai_constraints", "")

def _normalize_ai_draft(d:dict)->dict:
    d = dict(d or {})
    d.setdefault("title","New AI Recipe")
    d.setdefault("default_servings", 2)
    d.setdefault("time_min", 20)
    d.setdefault("difficulty","Easy")
    d.setdefault("course","Dinner")
    d.setdefault("cuisine","")
    d.setdefault("diet","")
    d.setdefault("tags", d.get("tags") or [])
    d.setdefault("allergens", d.get("allergens") or [])
    d.setdefault("kcal_per_serv", 0)
    d.setdefault("protein_g", 0)
    d.setdefault("carbs_g", 0)
    d.setdefault("fat_g", 0)
    d.setdefault("notes","")
    d.setdefault("components", [])
    d.setdefault("steps", [])
    # ensure component fields
    for c in d["components"]:
        c.setdefault("name","")
        c.setdefault("unit","g")
        c.setdefault("quantity_per_serving", 0.0)
        c.setdefault("staple", False)
        c.setdefault("optional", False)
        c.setdefault("yield_pct", 100.0)
        c.setdefault("wastage_pct", 0.0)
    for s in d["steps"]:
        s.setdefault("text","")
        s.setdefault("minutes",0)
        s.setdefault("equipment", s.get("equipment") or [])
    return d

def tab_ai_create(user_id:int):
    st.subheader("AI Create")
    _ensure_ai_draft()

    c1, c2 = st.columns([3,1])
    st.session_state["ai_constraints"] = c1.text_input(
        "Describe what you want (e.g., 'high-protein chicken dinner under 30 minutes, oven-free').",
        value=st.session_state.get("ai_constraints","")
    )
    gen_btn = c2.button("Generate", use_container_width=True)
    if gen_btn:
        data = rc.ai_generate_recipe(user_id, st.session_state["ai_constraints"])
        st.session_state[_ai_key()] = _normalize_ai_draft(data or {})
        st.rerun()

    draft = st.session_state.get(_ai_key())
    if not draft:
        st.info("Type constraints then click Generate. I’ll draft something edible.")
        return

    # Editing form
    with st.form("ai_edit_form", clear_on_submit=False):
        # Meta
        m1,m2,m3 = st.columns([2,1,1])
        draft["title"] = m1.text_input("Title", value=draft.get("title",""), key="ai_title")
        draft["default_servings"] = m2.number_input("Default servings", min_value=1, value=int(draft.get("default_servings",2)), step=1, key="ai_sv")
        draft["time_min"] = m3.number_input("Time (min)", min_value=1, value=int(draft.get("time_min",20)), step=5, key="ai_tm")
        m4,m5,m6 = st.columns([1,1,2])
        draft["difficulty"] = m4.selectbox("Difficulty", ["Easy","Medium","Hard"], index=["Easy","Medium","Hard"].index(draft.get("difficulty","Easy")), key="ai_diff")
        draft["course"] = m5.selectbox("Course", ["Dinner","Lunch","Breakfast","Dessert","Snack","Drink"],
                                       index=max(0, ["Dinner","Lunch","Breakfast","Dessert","Snack","Drink"].index(draft.get("course","Dinner"))) if draft.get("course","Dinner") in ["Dinner","Lunch","Breakfast","Dessert","Snack","Drink"] else 0,
                                       key="ai_course")
        draft["cuisine"] = m6.text_input("Cuisine", value=draft.get("cuisine",""), key="ai_cui")
        m7,m8 = st.columns([2,1])
        tags_csv = m7.text_input("Tags (comma)", value=",".join(draft.get("tags") or []), key="ai_tags")
        draft["tags"] = [t.strip() for t in tags_csv.split(",") if t.strip()]
        draft["diet"] = m8.text_input("Diet", value=draft.get("diet",""), key="ai_diet")

        allergens_all = ["gluten","dairy","nuts","soy","egg","fish","shellfish","sesame","vegan","vegetarian","halal","kosher"]
        draft["allergens"] = st.multiselect("Allergens", allergens_all, default=[a for a in draft.get("allergens") or [] if a in allergens_all], key="ai_allergens")

        n1,n2,n3,n4 = st.columns(4)
        draft["kcal_per_serv"] = n1.number_input("kcal / serving", min_value=0.0, value=float(draft.get("kcal_per_serv",0)), step=10.0, key="ai_kcal")
        draft["protein_g"] = n2.number_input("Protein g / serving", min_value=0.0, value=float(draft.get("protein_g",0)), step=1.0, key="ai_prot")
        draft["carbs_g"]   = n3.number_input("Carbs g / serving", min_value=0.0, value=float(draft.get("carbs_g",0)), step=1.0, key="ai_carbs")
        draft["fat_g"]     = n4.number_input("Fat g / serving",   min_value=0.0, value=float(draft.get("fat_g",0)), step=1.0, key="ai_fat")
        draft["notes"] = st.text_area("Notes / description", value=draft.get("notes",""), key="ai_notes")

        st.markdown("#### Ingredients")
        comps = draft.get("components") or []
        if not comps:
            comps.append({"name":"","unit":"g","quantity_per_serving":0.0,"staple":False,"optional":False,"yield_pct":100.0,"wastage_pct":0.0})
        for i, comp in enumerate(comps):
            c1,c2,c3,c4,c5,c6,c7,c8 = st.columns([3,1.2,1.2,0.9,0.9,1.0,1.0,0.6])
            comp["name"] = c1.text_input("Name", value=comp.get("name",""), key=f"ai_c_name_{i}")
            comp["unit"] = c2.selectbox("Unit", rc.UNITS, index=max(0, rc.UNITS.index(comp.get("unit","g"))) if comp.get("unit","g") in rc.UNITS else 0, key=f"ai_c_unit_{i}")
            comp["quantity_per_serving"] = c3.number_input("Qty/serv", min_value=0.0, value=float(comp.get("quantity_per_serving",0.0)), step=1.0, key=f"ai_c_qty_{i}")
            comp["staple"] = c4.checkbox("Staple", value=bool(comp.get("staple",False)), key=f"ai_c_st_{i}")
            comp["optional"] = c5.checkbox("Opt", value=bool(comp.get("optional",False)), key=f"ai_c_opt_{i}")
            comp["yield_pct"] = c6.number_input("Yield%", min_value=1.0, max_value=100.0, value=float(comp.get("yield_pct",100.0)), step=1.0, key=f"ai_c_y_{i}")
            comp["wastage_pct"] = c7.number_input("Waste%", min_value=0.0, max_value=90.0, value=float(comp.get("wastage_pct",0.0)), step=1.0, key=f"ai_c_w_{i}")
            if c8.form_submit_button("✕", key=f"ai_c_del_{i}"):
                del comps[i]; st.rerun()
        if st.form_submit_button("Add ingredient ➕", key="ai_add_ing"):
            comps.append({"name":"","unit":"g","quantity_per_serving":0.0,"staple":False,"optional":False,"yield_pct":100.0,"wastage_pct":0.0})
            st.rerun()

        st.markdown("#### Steps")
        steps = draft.get("steps") or []
        if not steps:
            steps.append({"text":"","minutes":0,"equipment":[]})
        for i, step in enumerate(steps):
            s1,s2,s3,s4,s5,s6 = st.columns([0.5,4.0,1.0,2.0,0.6,0.6])
            s1.write(str(i+1))
            step["text"] = s2.text_input("Text", value=step.get("text",""), key=f"ai_s_text_{i}")
            step["minutes"] = s3.number_input("Min", min_value=0, value=int(step.get("minutes",0)), key=f"ai_s_min_{i}")
            eq_txt = s4.text_input("Equipment (comma)", value=",".join(step.get("equipment",[])), key=f"ai_s_eq_{i}")
            step["equipment"] = [x.strip() for x in eq_txt.split(",") if x.strip()]
            if s5.form_submit_button("↑", key=f"ai_s_up_{i}") and i>0:
                steps[i-1], steps[i] = steps[i], steps[i-1]; st.rerun()
            if s6.form_submit_button("↓", key=f"ai_s_dn_{i}") and i < len(steps)-1:
                steps[i+1], steps[i] = steps[i], steps[i+1]; st.rerun()
        if st.form_submit_button("Add step ➕", key="ai_add_step"):
            steps.append({"text":"","minutes":0,"equipment":[]}); st.rerun()

        save = st.form_submit_button("Save to library ✅", use_container_width=True, key="ai_save")
        if save:
            try:
                rid = rc.persist_ai_recipe(user_id, _normalize_ai_draft(draft))
                st.success("Saved.")
                st.session_state[_ai_key()] = None
                st.session_state["recipe_view_id"] = rid
                _invalidate_cache()
                st.rerun()
            except Exception as e:
                st.error(f"Save failed: {e}")

    c3,c4 = st.columns([1,1])
    if c3.button("Reset draft", key="ai_reset"):
        st.session_state[_ai_key()] = None; st.rerun()
    if c4.button("Regenerate (replace)", key="ai_regen"):
        data = rc.ai_generate_recipe(user_id, st.session_state.get("ai_constraints",""))
        st.session_state[_ai_key()] = _normalize_ai_draft(data or {})
        st.rerun()

# ----------------------------- Detail view ------------------------------------

def _detail_ui(user_id:int, recipe_id:int):
    meta=rc.get_recipe_meta(recipe_id)
    if not meta:
        st.warning("Recipe not found."); return
    (title,dsv,tmin,diff,course,cuisine,diet,allergens,tags,kcal,prot,carbs,fat,rating,favorite,notes,photo)=meta

    st.divider(); st.markdown(f"### {title}")
    c1, c2 = st.columns([2,1])
    with c1:
        st.markdown("<div class='thumb'></div>", unsafe_allow_html=True)
        chips([t for t in (tags or '').split(',') if t.strip()])
        if allergens:
            st.caption("Allergens: " + ", ".join([a for a in allergens.split(",") if a]))
        st.caption(f"{course or 'Meal'} • {cuisine or '—'} • {diet or '—'}")
        st.caption(f"Nutrition/serv: {int(kcal or 0)} kcal, {prot}g P, {carbs}g C, {fat}g F")
        if notes: st.caption(notes)
    with c2:
        servings=st.number_input("Servings", min_value=1, value=int(dsv or 2), step=1, key=f"serv_{recipe_id}")
        cov=rc.coverage_for_recipe(recipe_id, int(servings))
        bar(cov["coverage_pct"])
        st.write(f"Coverage **{cov['coverage_pct']}%**  •  Cost **₪{cov['cost_total']:.2f}**  •  ₪/portion **{cov['cost_per_portion']:.2f}**")
        if cov["max_cookable"]>0 and st.button(f"Max cookable: {cov['max_cookable']}", key=f"mx{recipe_id}"):
            st.session_state[f"serv_{recipe_id}"]=cov["max_cookable"]; st.rerun()
        c1b,c2b,c3b=st.columns(3)
        if c1b.button("Cook now", disabled=cov["status"]=="err", key=f"cook{recipe_id}"):
            ok,msg=rc.cook_recipe(user_id, recipe_id, int(servings))
            st.success(msg) if ok else st.error(msg)
            if ok:
                _invalidate_cache()
                st.balloons()
                st.rerun()
        if c2b.button("Favorite ★" if not favorite else "Unfavorite ☆", key=f"fav_t{recipe_id}"):
            conn=rc.get_connection()
            conn.execute("UPDATE recipes_catalog SET favorite=? WHERE id=?", (0 if favorite else 1, recipe_id))
            conn.commit(); conn.close()
            st.rerun()
        if c3b.button("Delete", key=f"del{recipe_id}"):
            conn=rc.get_connection()
            conn.execute("DELETE FROM recipe_steps WHERE recipe_id=?", (recipe_id,))
            conn.execute("DELETE FROM recipes_catalog_components WHERE recipe_id=?", (recipe_id,))
            conn.commit(); conn.close()
            st.success("Deleted.")
            st.session_state.pop("recipe_view_id", None)
            st.rerun()

    # Repair utilities
    st.markdown("#### Ingredients")
    util1, util2, util3 = st.columns([1,1,2])
    if util1.button("Fix staples for this recipe"):
        rc.recompute_staples_for_recipe(recipe_id)
        _invalidate_cache(); st.rerun()
    if util2.button("Relink to stocked items"):
        changed = rc.repair_links_for_recipe(recipe_id)
        _invalidate_cache()
        st.success(f"Relinked {changed} component(s).")
        st.rerun()
    show_diag = util3.checkbox("Show debug mapping", value=False, key=f"dbg{recipe_id}")

    comps=rc.get_recipe_components(recipe_id)
    cov=rc.coverage_for_recipe(recipe_id, int(st.session_state.get(f"serv_{recipe_id}", dsv or 2)))
    cov_by_name={i["name"]:i for i in cov["items"]}

    used_alt_any = any(i.get("alt_used", False) for i in cov["items"])
    if used_alt_any:
        st.markdown("<div class='note'>Coverage used a stocked alternative for at least one ingredient. Use <b>Relink to stocked items</b> to make it permanent.</div>", unsafe_allow_html=True)

    # Table-ish listing
    for (_cid, ing_id, nm, bu, have, ppb, inv_type, q_base_def, is_staple, is_opt, y, wst, cat, sku, subs, note, tc) in comps:
        ci=cov_by_name.get(nm, None)
        need = ci["need_base"] if ci else 0.0
        have_show = ci["have_base"] if ci else float(have or 0.0)  # show coverage "have" (includes alt)
        short = ci["short_base"] if ci else 0.0
        status = ci["status"] if ci else "err"
        alt_used = bool(ci.get("alt_used", False)) if ci else False

        a,b,c,d,e,f,g,h = st.columns([3,2,2,2,2,1,1,1.2])
        a.write(nm)
        b.write(f"need {need:.1f} {bu}")
        c.write(f"have {have_show:.1f} {bu}")
        d.write("—" if short<=0 else f"short {short:.1f} {bu}")
        e.write(cat or "—")
        f.markdown(f"<span class='chip {status}'>{'staple' if (is_staple and rc._is_staple_name(nm)) else status}</span>", unsafe_allow_html=True)
        new_val = g.checkbox("staple", value=bool(is_staple), key=f"staple_{_cid}")
        if new_val != bool(is_staple):
            rc.set_component_staple(_cid, new_val); st.rerun()
        if alt_used:
            h.markdown("<span class='chip warn'>alt stock</span>", unsafe_allow_html=True)
        else:
            h.write("")

    if show_diag:
        st.markdown("#### Debug link map")
        diag = rc.diagnose_recipe_links(recipe_id)
        if not diag:
            st.info("No diagnostics available.")
        else:
            ha, hb, hc, hd, he = st.columns([3,2,2,2,2])
            ha.write("**Name**"); hb.write("**Linked item id**"); hc.write("**Linked have**"); hd.write("**Alt item id**"); he.write("**Alt differs**")
            for row in diag:
                a,b,c,d,e = st.columns([3,2,2,2,2])
                a.write(row["name"])
                b.write(str(row["linked_item_id"]))
                c.write(f"{row['linked_have']:.1f}")
                d.write(str(row["alt_item_id"] or "—"))
                e.write("yes" if row["alt_is_different"] else "no")

    if st.session_state.get("recipe_cook_now"):
        st.session_state.pop("recipe_cook_now", None)
        ok,msg=rc.cook_recipe(user_id, recipe_id, int(st.session_state.get(f"serv_{recipe_id}", dsv or 2)))
        st.success(msg) if ok else st.error(msg)
        if ok:
            _invalidate_cache()
            st.balloons()
        st.rerun()

# ----------------------------- Cook Now tab -----------------------------------

def tab_cook_now(user_id:int):
    st.subheader("Cook Now")
    recs=rc.get_recipes(user_id)
    if not recs:
        st.info("No recipes yet."); return

    def rescue_score(rid:int)->float:
        today=date.today(); score=0.0
        for r in rc.get_recipe_components(rid):
            (_cid, ing_id, nm, bu, have, ppb, inv_type, q_base_def, is_staple, is_opt, y, wst, cat, sku, subs, note, tc)=r
            if int(is_staple or 0)==1 or rc._is_staple_name(nm or ""): continue
            conn=rc.get_connection(); c=conn.cursor()
            c.execute("SELECT COALESCE(expiration,'2099-12-31'), COALESCE(price_per_base,0), COALESCE(base_amount,0), COALESCE(total_cost,0) FROM inventory WHERE id=?", (ing_id,))
            rr=c.fetchone(); conn.close()
            if not rr: continue
            exp, ppbX, amt, tc = rr
            try:
                days=(date.fromisoformat(exp)-today).days
            except:
                days=30
            urgency=max(0.0,min(1.0,(14-days)/14.0))
            need = q_base_def * (100.0+float(wst or 0))/100.0 / max(0.01, float(y or 100)/100.0)
            price = float(ppbX or 0.0)
            if price<=0 and float(tc or 0)>0 and float(amt or 0)>0:
                price=float(tc)/float(amt)
            score += urgency * price * min(float(amt or 0.0), float(need or 0.0))
        return score

    ranked=sorted(recs, key=lambda r: rescue_score(r[0]), reverse=True)
    for r in ranked[:20]:
        rid=r[0]; cov=rc.coverage_for_recipe(rid, int(r[2] or 2))
        a,b,c,d = st.columns([3,2,2,1])
        a.write(f"**{r[1]}**")
        b.write(f"Coverage {cov['coverage_pct']}%")
        c.write(f"₪/portion {cov['cost_per_portion']:.2f}")
        if d.button("Cook", disabled=cov['status']=="err", key=f"cookk{rid}"):
            ok,msg=rc.cook_recipe(user_id, rid, int(r[2] or 2))
            st.success(msg) if ok else st.error(msg)
            if ok:
                _invalidate_cache()
                st.balloons()
                st.rerun()

# ----------------------------- Settings tab -----------------------------------

def tab_settings(user_id:int):
    st.subheader("Settings")
    cur=cached_staples()
    with st.form("staples_form"):
        txt=st.text_area("Staples (one per line)", value="\n".join(cur))
        if st.form_submit_button("Save staples", key="save_staples_btn"):
            xs=[x.strip().lower() for x in txt.splitlines() if x.strip()]
            conn=rc.get_connection(); c=conn.cursor()
            c.execute("DELETE FROM staples")
            c.executemany("INSERT INTO staples(name) VALUES (?)", [(x,) for x in xs])
            conn.commit(); conn.close()
            _invalidate_cache()
            st.success("Saved staples.")
    st.markdown("---")
    r1,r2 = st.columns([1,2])
    if r1.button("Hard reset staples (ALL recipes)"):
        touched=rc.reset_all_staples_to_defaults(user_id)
        _invalidate_cache()
        st.success(f"Reset staple flags on {touched} components.")
    if r2.button("Repair links on ALL recipes (stock-aware)"):
        total=0
        for rid, *_ in rc.get_recipes(user_id):
            total += rc.repair_links_for_recipe(rid)
        _invalidate_cache()
        st.success(f"Relinked {total} component(s) across all recipes.")

# ----------------------------- Entry points -----------------------------------

def recipes_page():
    inject_theme()
    rc.ensure_schema()

    if "user_id" not in st.session_state:
        st.warning("Please log in first."); st.stop()
    user_id=int(st.session_state["user_id"])

    st.title("🍽️ Recipes")
    tabs = st.tabs(["Library","Create","AI Create","Cook Now","Settings"])
    with tabs[0]: tab_library(user_id)
    with tabs[1]: tab_create(user_id)
    with tabs[2]: tab_ai_create(user_id)        # ← new tab
    with tabs[3]: tab_cook_now(user_id)
    with tabs[4]: tab_settings(user_id)

def render():
    recipes_page()
