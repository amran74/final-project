# Inventory.py — clean, focused inventory
import streamlit as st
from datetime import datetime, date
import db

def add_item(user_id, name, expiration, food_type, amount, unit, stable=False, price_per_unit=0.0):
    conn = get_connection(); c = conn.cursor()
    c.execute("""INSERT INTO inventory
        (user_id, name, expiration, type, amount, unit, used_count, last_used_month, stable, price_per_unit)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)""",
        (user_id, name, expiration, food_type, amount, unit, date.today().strftime("%Y-%m"), int(stable), price_per_unit))
    conn.commit(); conn.close()

def get_user_items(user_id):
    conn = get_connection(); c = conn.cursor()
    c.execute("""SELECT id,name,expiration,type,amount,unit,used_count,last_used_month,stable,price_per_unit,
                        COALESCE(expired_count,0), COALESCE(money_lost,0.0)
                 FROM inventory WHERE user_id=? ORDER BY date(expiration) ASC, name ASC""", (user_id,))
    rows = c.fetchall(); conn.close(); return rows

def delete_item(item_id):
    conn = get_connection(); c = conn.cursor()
    c.execute("DELETE FROM inventory WHERE id=?", (item_id,))
    conn.commit(); conn.close()

def inventory():
    st.title("📦 Inventory")
    if "user_id" not in st.session_state:
        st.warning("Login first."); st.stop()
    user_id = st.session_state["user_id"]

    # Add form
    with st.form("add_item", clear_on_submit=True):
        c1,c2,c3 = st.columns([2,1.2,1])
        name = c1.text_input("Name")
        exp  = c2.date_input("Expiration", min_value=date.today())
        typ  = c3.selectbox("Type", ["Dairy","Fruit","Meat","Grain","Vegetable","Other"])
        c4,c5,c6 = st.columns([1,1,1])
        amount = c4.number_input("Amount", min_value=0.0, step=1.0, value=1.0)
        unit   = c5.selectbox("Unit", ["pcs","g","kg","ml","l"])
        ppu    = c6.number_input("₪/unit", min_value=0.0, step=0.1, value=0.0)
        stable = st.checkbox("⚖️ Stable item (keep visible at 0)")
        if st.form_submit_button("Add"):
            if not name.strip(): st.error("Name required.")
            else:
                add_item(user_id, name.strip(), exp.strftime("%Y-%m-%d"), typ, float(amount), unit, stable, float(ppu))
                st.success("Added."); st.rerun()

    # List
    rows = get_user_items(user_id)
    if not rows:
        st.info("Empty. Add something."); return

    colA, colB = st.columns(2)
    for i, r in enumerate(rows):
        (item_id, name, exp, typ, amount, unit, used_count, last_m, stable, ppu, expired_steps, money_lost) = r
        dleft = (datetime.strptime(exp, "%Y-%m-%d").date() - date.today()).days
        status, color = ("Expired","#FF4B4B") if dleft < 0 else (("Expiring Soon","#FFA500") if dleft<=2 else ("Fresh","#4CAF50"))
        host = colA if i%2==0 else colB
        with host:
            st.markdown(f"""
                <div style='background:#1f1f1f;border-left:6px solid {color};padding:14px 16px;border-radius:12px;margin-bottom:12px'>
                  <h4 style='margin:0;color:#fafafa'>{name} <span style='font-size:12px;color:#888;'>({typ})</span></h4>
                  <p style='margin:4px 0;color:#ccc;'>📅 <b>Expires:</b> {exp} &nbsp; | &nbsp; 🔔 <b>{status}</b></p>
                  <p style='margin:4px 0;color:#ccc;'>🔢 <b>Amount:</b> {amount} {unit} &nbsp; | &nbsp; 💲 <b>₪/unit:</b> {ppu}</p>
                  <p style='margin:4px 0;color:#ccc;'>✅ Used this month: {used_count} &nbsp; | &nbsp; 🗑️ Expired steps: {expired_steps} &nbsp; | &nbsp; 💸 Lost: ₪{round(money_lost,2)}</p>
                  {"<p style='margin:4px 0;color:#0ff;'>⚖️ Stable Item</p>" if stable else ""}
                </div>
            """, unsafe_allow_html=True)

            # actions
            a1,a2,a3,a4 = st.columns([1.2,1.2,1.2,1])
            if a1.button("✅ Use 1", key=f"use1_{item_id}"):
                try: use_one_step(item_id); st.success("Used 1 step.")
                except Exception as e: st.error(e)
                st.rerun()

            step = 0.1 if unit in ("kg","l","lt","liter","litre") else (100.0 if unit in ("g","ml") else 1.0)
            qty = a2.number_input("Qty", min_value=0.0, step=step, key=f"qty_{item_id}")

            if a3.button("🍴 Use qty", key=f"useqty_{item_id}"):
                try: res = use_item(item_id, float(qty)); st.success(f"Used +{res['used_step_added']} steps.")
                except Exception as e: st.error(e)
                st.rerun()

            if a4.button("☠️ Expire ALL", key=f"expall_{item_id}"):
                try: expire_all(item_id); st.error("Expired all.")
                except Exception as e: st.error(e)
                st.rerun()

            b1,b2,b3 = st.columns([1.2,1.2,1])
            if b1.button("🧪 Expire qty", key=f"expqty_{item_id}"):
                try: res = expire_item(item_id, float(qty)); st.warning(f"Expired +{res['expired_step_added']} steps.")
                except Exception as e: st.error(e)
                st.rerun()

            with b2.expander("✏️ Edit"):
                new_name = st.text_input("Name", value=name, key=f"nm_{item_id}")
                new_exp  = st.date_input("Expiration", value=datetime.strptime(exp,"%Y-%m-%d").date(), key=f"ex_{item_id}")
                new_typ  = st.text_input("Type", value=typ, key=f"tp_{item_id}")
                new_amt  = st.number_input("Amount", min_value=0.0, value=float(amount), step=step, key=f"am_{item_id}")
                new_unit = st.selectbox("Unit", ["pcs","g","kg","ml","l"],
                                        index=["pcs","g","kg","ml","l"].index(unit) if unit in ["pcs","g","kg","ml","l"] else 0,
                                        key=f"un_{item_id}")
                new_ppu  = st.number_input("₪/unit", min_value=0.0, value=float(ppu or 0.0), step=0.1, key=f"pr_{item_id}")
                if st.button("💾 Save", key=f"save_{item_id}"):
                    try: db_update_item(item_id, new_name.strip(), new_exp.strftime("%Y-%m-%d"), new_typ, float(new_amt), new_unit, float(new_ppu)); st.success("Saved.")
                    except Exception as e: st.error(e)
                    st.rerun()

            if b3.button("🗑️ Delete", key=f"del_{item_id}"):
                delete_item(item_id); st.rerun()
