# Smart Inventory & AI Analytics Platform

A full-featured inventory management and analytics system built with **Python** and **Streamlit**, designed around real retail workflows and data-driven decision-making.  
The app tracks stock, expiry, consumption behavior, and exposes this through dashboards and KPIs for managers.

---

## Features

### 🔹 Inventory Management
- Add, edit, delete items
- Track:
  - Quantity
  - Expiry date
  - Category / department
  - Supplier (optional, if configured)
- “Stable items” remain visible even at zero quantity (so critical items never disappear)
- Automatic cleanup of expired items (configurable logic)
- Monthly usage tracking per item

### 🔹 Data & Analytics Focus
- Monthly usage table and charts for each item and/or category
- Identify:
  - Fast-moving vs slow-moving products
  - Items frequently running out
  - Items commonly expiring on the shelf
- Category-level summaries:
  - Total quantity
  - Average remaining shelf time
  - Number of risky / low-stock items
- Support for shrinkage / loss analysis via:
  - Differences between expected and actual quantities
  - Expired vs consumed breakdowns (where data is available)

### 🔹 Excel Integration
- Import data from Excel files into the system
- Bulk-load or update inventory from structured spreadsheets
- Use imported Excel data directly in:
  - Inventory tables
  - Dashboards
  - AI assistant analysis
- Basic validation/cleaning when reading from Excel to avoid corrupting the database

### 🔹 Dashboards & KPIs
- Visual dashboards for:
  - Usage over time (by item or category)
  - Expiry trends
  - Low-stock trends
- KPIs designed for retail / pharmacy environments, for example:
  - Number of items below minimum threshold
  - Number of items expiring this week / month
  - Items with repeated expiry issues
- Filters by:
  - Date range
  - Category / department
  - Status (OK / low / expiring / expired)

### 🔹 AI Assistant
- Integrated **OpenAI API** for contextual help:
  - Explain inventory trends in plain language
  - Suggest actions (e.g., “which items should I reorder first?”)
  - Help formulate messages, notes, or procedures based on the current inventory state
- The assistant works on top of the actual data in the database and imported Excel files, not imaginary numbers

### 🔹 Authentication System
- Login & registration using **SQLite**
- Password hashing for safer storage
- Stores:
  - Full name
  - Phone number (for identification inside the app, not for messaging)
- Personalized greetings on login
- “Forgot password” flow using stored data

### 🔹 Multi-Page Streamlit App
- Home / Dashboard page with:
  - Calendar widget
  - Quick navigation to main modules
  - High-level KPIs
- Inventory page for CRUD operations
- Analytics / Dashboards page for charts and tables
- AI Assistant page for conversational interaction with your data
- Top navigation bar visible on all pages

### 🔹 UI/UX
- Clean Streamlit-based interface
- Logical separation between:
  - Operational actions (add/edit items)
  - Analytical views (dashboards)
  - Intelligent help (AI assistant)
- Designed to be usable with mouse only, no technical knowledge required

---

## Tech Stack

- Python
- Streamlit
- SQLite
- Pandas / NumPy
- OpenAI API
- Plotly / Matplotlib (for charts and visualizations)

---

## Project Structure

project/
    home.py           - Login/Register screen
    homepage.py       - Main homepage with calendar + KPIs
    inventory.py      - Inventory management UI + logic
    assistant.py      - AI assistant interface
    dashboards.py     - Analytics & charts
    database.py       - SQLite models & DB utilities
    utils.py          - Shared helper functions
    README.md

---

## Installation

1. Clone the repository

    git clone <repo-url>
    cd <project-folder>

2. Install dependencies

    pip install -r requirements.txt

3. Run the app

    streamlit run home.py

---

## Configuration

Create a .env file in the project root with:

    OPENAI_API_KEY=your_openai_key_here

Add any additional environment variables (e.g. DB path overrides) here if needed.

---

## Future Improvements

- Role-based access (admin / manager / staff)
- More advanced analytics:
  - Forecasting demand based on historical usage
  - Automatic reorder suggestions
- Exportable reports (CSV / PDF)
- Optional integration with external ERP / POS systems
- More detailed shrinkage tracking and reconciliation tooling
