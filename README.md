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
- Bulk-load or update inventory from spreadsheets
- Use imported Excel data directly in:
  - Inventory tables
  - Dashboards
  - AI assistant analysis
- Basic validation when reading from Excel to avoid corrupting the database

### 🔹 Dashboards & KPIs
- Visual dashboards for:
  - Usage over time (by item or category)
  - Expiry trends
  - Low-stock trends
- KPIs for retail/pharmacy-style environments:
  - Items below minimum threshold
  - Items expiring soon
  - Items with repeated expiry issues
- Filters by date range, category, and item status

### 🔹 AI Assistant
- Integrated **OpenAI API** for contextual help:
  - Explain inventory trends in simple language
  - Suggest operational steps
  - Help write notes or procedures
- Works directly on top of the real database and Excel-imported data

### 🔹 Authentication System
- Login & registration through **SQLite**
- Secure password hashing
- Stores:
  - Full name
  - Phone number (for internal use)
- Personalized greeting
- Forgot-password page

### 🔹 Multi-Page Streamlit App
- Homepage with calendar + KPIs + quick navigation
- Inventory CRUD interface
- Dashboards & analytics
- AI assistant interface
- Top navigation bar on all pages

### 🔹 UI/UX
- Clean Streamlit-only design
- Separation between operational, analytical, and AI components
- Fully mouse-friendly workflow with zero technical requirements

---

## Tech Stack

- Python
- Streamlit
- SQLite
- Pandas / NumPy
- OpenAI API
- Plotly / Matplotlib

---

## Project Structure

project/
    home.py           - Login/Register
    homepage.py       - Dashboard home with KPIs
    inventory.py      - Inventory management
    assistant.py      - AI assistant
    dashboards.py     - Analytics visualizations
    database.py       - SQLite models + utility functions
    utils.py          - Shared helpers
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

Create a .env file in the project root:

    OPENAI_API_KEY=your_openai_key_here

Add additional environment variables as needed.

---

## Future Improvements

- Role-based access (admin / manager / staff)
- Integration with **business cashier / POS** so every order:
    - Automatically reduces stock for the sold items
    - Logs consumption into monthly usage tables
    - Updates item costs and profitability metrics
- Demand forecasting using historical usage
- Automatic reorder suggestions
- POS-level shrinkage reconciliation
- PDF report exports for audits and management
