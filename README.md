# Smart Inventory & AI Analytics Platform

A full-featured inventory management system built with **Python** and **Streamlit**, designed for real-world retail operations. The system integrates automated alerts, an AI assistant, dashboards, per-user accounts, and full WhatsApp notifications.

## Features

### 🔹 Inventory Management
- Add, edit, delete items  
- Track quantities, expiry dates, and item categories  
- Stable items remain visible even at zero quantity  
- Automatic deletion of expired items  
- Monthly usage tracking for each product

### 🔹 AI Assistant
- Integrated OpenAI API for contextual assistance  
- Explains inventory insights  
- Helps write product notes, messages, or operational instructions  
- Responds based on real inventory state

### 🔹 Notifications (WhatsApp)
- Twilio integration for WhatsApp alerts  
- Sends notifications for:  
  - Expiring items  
  - Items reaching minimum quantity  
  - Full inventory reports  
- Per-user phone numbers (each user receives their own alerts)

### 🔹 Authentication System
- Login & registration using SQLite  
- Encrypted passwords  
- Stores phone numbers and full name  
- Personalized welcome messages  
- "Forgot password" support

### 🔹 Multi-Page Streamlit App
- Homepage with calendar and quick menu  
- Always-visible top navigation bar  
- Inventory Page  
- AI Assistant Page  
- Dashboards Page

### 🔹 Dashboards & Analytics
- Monthly usage visualizations  
- Category-level insights  
- Stock risk analysis  
- Expiry trends  
- KPIs integrated to help retail managers understand shrinkage and stock behavior

### 🔹 UI/UX
- Clean modern interface  
- Improved homepage with reduced calendar dominance  
- Menu shortcuts for fast navigation  
- Designed without CSS/JS (Streamlit-only)

---

## Tech Stack

- **Python**
- **Streamlit**
- **SQLite**
- **Pandas / NumPy**
- **OpenAI API**
- **Twilio API (WhatsApp)**
- **Plotly / Matplotlib** for dashboards

---

## Project Structure

\\\
project/
│
├── home.py              # Login/Register page
├── homepage.py          # Main homepage with calendar
├── inventory.py         # Inventory management
├── assistant.py         # AI assistant
├── dashboards.py        # Analytics & charts
├── database.py          # SQLite models & functions
├── utils.py             # Shared helper functions
└── README.md
\\\

---

## Installation

### 1. Clone the repository
\\\
git clone <repo-url>
cd <project-folder>
\\\

### 2. Install dependencies
\\\
pip install -r requirements.txt
\\\

### 3. Run the app
\\\
streamlit run home.py
\\\

---

## Setup

### Configure environment variables  
Create a \.env\ file with:

\\\
OPENAI_API_KEY=your_key
TWILIO_SID=your_sid
TWILIO_TOKEN=your_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+your_twilio_number
\\\

---

## Future Improvements
- Multi-user roles (admin / manager / employee)  
- Full audit logs  
- Barcode scanning  
- Exportable reports  
- Cloud database integration  
