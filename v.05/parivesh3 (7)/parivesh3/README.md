# PARIVESH 3.0 — Environmental Clearance Workflow Portal (Upgraded)

A complete government-grade environmental clearance management system with AI-assisted
pre-screening, sector-specific document checklists, meeting management, and transparent
case tracking.

---

## Quick Start (Local — Zero Extra Dependencies)

```bash
cd parivesh3

# Install only Flask + Werkzeug (stdlib sqlite3 used for DB)
pip install flask werkzeug python-dotenv gunicorn

# Seed with demo data
cd backend
python seed.py

# Start server
python app.py
```

Open **http://localhost:5000**

---

## Demo Credentials

| Role      | Email                      | Password  |
|-----------|----------------------------|-----------|
| Admin     | admin@parivesh.gov.in      | admin123  |
| PP        | rahul@infra.com            | test123   |
| PP        | sunita@mining.com          | test123   |
| Scrutiny  | priya@scrutiny.gov.in      | test123   |
| MoM       | anil@mom.gov.in            | test123   |

---

## What's New in this Upgrade

### 🤖 AI Pre-Screening Engine
- Runs automatically on application submission
- Checks: mandatory docs, affidavit, file types, project details, EMP, processing fee
- Score 0–100%; passes to Scrutiny or raises EDS with detailed report
- AI report shown on Case File page with score ring, issues, and checks passed

### 📋 Sector-Specific Document Checklist Engine
- 8 sectors: Sand Mining, Limestone Mining, Brick Kiln, Infrastructure, Industry, Energy, Coastal, Other
- Each sector has mandatory + optional document lists
- Application form shows interactive checklist with upload per document
- Backend blocks submission if required docs appear missing

### 📜 Affidavit System
- Separate affidavit upload step with 6 affidavit types
- Stored with `is_affidavit` flag in database
- AI screening checks affidavit presence
- Shown with special badge in document history

### 📅 Meeting Management System
- Schedule EAC meetings with application ID, date, and agenda
- AI Gist document auto-generated from application data
- Meeting notes editor with status tracking (Scheduled/Completed/Cancelled)
- Dedicated `/meetings` page

### 🤖 AI Gist Generation
- Auto-generates a structured Gist document from application data
- Includes project details, documents list, EDS history, meeting history
- Available from Case File page and Meetings page
- One-click copy to clipboard

### 💬 AI Chatbot
- Available on all pages (floating button bottom-right)
- Answers questions about: documents, sectors, EDS, submission, AI screening, meetings, affidavits
- Knowledge base covers entire clearance workflow

### 🔍 Global Search in Topbar
- Search bar in topbar searches across all applications
- Auto-redirects to matching case file or filtered dashboard

### 📱 Fully Responsive Design
- Works on desktop, tablet, and mobile
- Sidebar hidden on mobile
- Grid layouts collapse to single column
- Topbar search hidden on small screens

---

## Workflow Pipeline

```
Draft → Submitted → AIScreening → Scrutiny → EDS → Resubmitted → Referred → MoMGenerated → Finalized
```

## File Structure

```
parivesh3/
├── backend/
│   ├── app.py              ← Flask app factory
│   ├── db.py               ← SQLite layer (stdlib only, no ORM)
│   ├── ai_screening.py     ← Rule-based AI engine + Gist generator
│   ├── seed.py             ← Rich demo data seeder
│   └── routes/
│       ├── auth.py         ← Auth (register/login/roles)
│       └── applications.py ← Full workflow + meetings + chatbot
├── frontend/
│   ├── login.html          ← Login + register tabs
│   ├── dashboard.html      ← Application list with AI scores
│   ├── application_form.html ← Multi-step form with sector checklist
│   ├── case_file.html      ← Digital case file + AI report + timeline
│   ├── scrutiny.html       ← Scrutiny queue dashboard
│   ├── meetings.html       ← Meeting management + gist viewer
│   ├── mom.html            ← MoM secretariat dashboard
│   └── admin.html          ← User management
├── static/
│   ├── css/style.css       ← Full responsive design system
│   └── js/
│       ├── app.js          ← API utils, chatbot, toast, search
│       └── shell.js        ← Topbar, sidebar, chatbot widget
├── uploads/                ← Secure file storage
├── Dockerfile
├── docker-compose.yml
├── Procfile
└── requirements.txt
```

## API Reference (New Endpoints)

| Method | Endpoint                        | Description                    |
|--------|---------------------------------|--------------------------------|
| GET    | /api/sectors                    | List all sectors               |
| GET    | /api/checklist/:sector          | Get sector document checklist  |
| POST   | /api/application/:id/upload     | Upload single document to draft|
| POST   | /api/scrutiny/verify/:id        | Mark documents verified        |
| GET    | /api/ai-report/:id              | Get AI screening report        |
| GET    | /api/application/:id/gist       | Generate AI gist document      |
| GET    | /api/meetings                   | List all meetings              |
| POST   | /api/meetings/create            | Create meeting + auto gist     |
| GET    | /api/meetings/:id               | Get single meeting             |
| POST   | /api/meetings/:id/update        | Update meeting notes/status    |
| GET    | /api/meetings/:id/gist          | Get/refresh meeting gist       |
| POST   | /api/chatbot                    | AI chatbot query               |

## Deployment

### Docker
```bash
cp .env.example .env
docker-compose up -d
```

### Render / Railway
Push to GitHub, connect repo.
- Build: `pip install -r requirements.txt`
- Start: `gunicorn --chdir backend --bind 0.0.0.0:$PORT "app:create_app()"`

### Fly.io
```bash
fly launch && fly secrets set SECRET_KEY=your-key && fly deploy
```
