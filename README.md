# Smart Inventory & AI Analytics Platform

A modular Python & Streamlit application for managing household or small-business inventory, planning recipes, minimizing waste, and generating insights with integrated AI assistance.

The system is built as a **multi-page app with separate logic cores**, a clean UI, and SQLite as a lightweight embedded database.  
It focuses on **data accuracy, expiry management, waste reduction, cost calculation, and daily planning**.

---

## 🚀 Features

### 🧺 Inventory Management
- Add, edit, and track inventory items  
- Track:
  - Expiry dates  
  - Category / type  
  - Quantity in base units (g / ml / pcs)  
  - Price per unit  
  - Cost per item  
- Stable items remain visible at zero quantity  
- Automatic cleanup of expired items on load  
- Full inventory overview with color-coded freshness indicators  
- Export inventory to **Excel/CSV**

---

### 📊 Dashboards & Analytics
- Usage over time (logged through recipe cooking, SmartCoach actions, and manual usage)  
- Expiry risk visualization  
- Low-stock detection  
- Category-level metrics  
- KPIs shown on homepage and dashboard page  
- Interactive charts powered by **Plotly** and **Streamlit**

---

### 🧠 SmartCoach (Waste Minimizer)
A decision-engine that prioritizes your daily actions:

- **Critical**: already expired or expires today  
- **Urgent**: expires in 1–3 days  
- **Preventive**: expires in 4–7 days  
- **Recipe Rescue**: recipes that help consume at-risk items  

Actions supported:
- Freeze  
- Use  
- Throw  
- Dismiss / Snooze  

All actions are logged into a dedicated tracking table.

---

### 🍽 Recipe System
- Build recipes with:
  - linked inventory ingredients  
  - optional ingredients  
  - yield percentages  
  - equipment  
  - cooking steps  
- Automatic **cost estimation**  
- **Coverage calculation**: how much of the recipe you can cook with current inventory  
- When cooking:
  - Inventory quantities are deducted  
  - Usage events are logged  
- Export recipe data for personal use

---

### 🛒 Shopping List Planner
- Builds shopping lists based on:
  - Missing recipe ingredients  
  - Low-stock inventory  
- Helps plan replenishment and reduce shortages  

---

### 🤖 AI Assistant
Uses the OpenAI API to:
- Explain trends  
- Recommend usage priorities  
- Suggest new recipes based on inventory  
- Generate notes, summaries, and ideas  
- Works directly on current database state (no mock data)

---

### 🔐 Authentication
- Login & register system  
- Password hashing  
- Each user gets their own inventory, recipes, and coach data  
- Personalized homepage with KPIs and calendar

---

## 🧱 Technology Stack

- **Python**  
- **Streamlit** (multi-page UI)  
- **SQLite**  
- **Pandas / NumPy**  
- **Plotly**  
- **OpenAI API**  

---

## 📁 Project Structure (Accurate)

\\\
App.py                  → Main app router
home.py                 → Login / Register / Session

CalendarView.py         → Homepage (KPIs + calendar)
Inventory.py            → Inventory UI
RecipesPage.py          → Recipes UI
Shopping.py             → Shopping list UI
SmartCoach.py           → SmartCoach UI
dashboard.py            → Dashboards UI

inventory_core.py       → Inventory logic
recipes_core.py         → Recipe logic & cost engine
shopping_core.py        → Shopping logic
smartcoach_core.py      → SmartCoach logic
dashboards_core.py      → KPI and chart logic
ai_commands_core.py     → AI utility commands
pricing.py              → Price calculation helpers
db.py                   → SQLite layer & schema handling
reset_db.py             → DB utilities
fix_schema.py           → Schema repair scripts

assets/                 → Images & banners
thumbs/                 → Icons
old/                    → Legacy prototype code
\\\

---

## 📦 Installation

\\\
pip install -r requirements.txt
streamlit run App.py
\\\

Create a .env file:

\\\
OPENAI_API_KEY=your_openai_key_here
\\\

---

## ⏭ Roadmap (Realistic)

- POS / cashier integration  
- Demand forecasting using historical logs  
- Auto-generated reorder suggestions  
- Multi-store support  
- PDF reporting  
- Excel **import** (future)  

---

## 🎯 Summary

This project demonstrates:

- Clean modular architecture  
- Separation of UI and core logic  
- Real-time expiry and cost management  
- Custom analytics layer  
- AI-driven guidance  
- Full lifecycle: inventory → recipes → usage logs → dashboards → recommendations  

A practical, real product — not a toy demo.
