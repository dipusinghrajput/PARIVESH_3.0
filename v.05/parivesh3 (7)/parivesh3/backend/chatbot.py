"""
chatbot.py — PARIVESH Assistant
================================
A fully independent, plug-and-play rule-based chatbot module for PARIVESH 3.0.

Features:
  • Rich static knowledge base covering the entire EC workflow
  • Live application status lookup from the database
  • Processing-days calculation
  • Estimated completion time (stage-based rules)
  • Latest timeline event retrieval
  • Multi-keyword intent matching with priority scoring
  • Graceful fallback with suggested questions
  • Application-ID extraction from free-form messages

Integration (3 steps):
  1. Copy this file into backend/
  2. In routes/applications.py, replace the /chatbot route body with:
         from chatbot import PariveshChatbot
         bot = PariveshChatbot()
         ...
         return jsonify({'reply': bot.reply(msg, user_id, app_id_hint)})
  3. The frontend widget is already present — no changes needed there.
"""

import re
import db
from datetime import datetime, timezone


# ── STAGE METADATA ────────────────────────────────────────────────────────────
STAGE_INFO = {
    'Draft': {
        'label':   'Draft',
        'icon':    '📝',
        'desc':    'Application is saved but not yet submitted. Upload your sector-specific documents and affidavit, then click Submit.',
        'action':  'Open your application and click "Submit & Run AI Screen".',
        'typical_days': 0,
    },
    'Submitted': {
        'label':   'Submitted',
        'icon':    '📬',
        'desc':    'Application submitted. AI pre-screening is running automatically.',
        'action':  'Wait for AI pre-screen result — usually within minutes.',
        'typical_days': 0,
    },
    'AIScreening': {
        'label':   'AI Screening',
        'icon':    '🤖',
        'desc':    'Automated AI engine is checking your documents against the sector checklist.',
        'action':  'No action needed. Result will be available shortly.',
        'typical_days': 1,
    },
    'Scrutiny': {
        'label':   'Under Scrutiny',
        'icon':    '🔍',
        'desc':    'A Scrutiny Officer is reviewing your application and all uploaded documents.',
        'action':  'No action needed. Be available for any clarifications the officer may seek.',
        'typical_days': 7,
    },
    'EDS': {
        'label':   'EDS Raised',
        'icon':    '🔴',
        'desc':    'Environmental Data Shortfall raised — one or more documents are missing or need correction.',
        'action':  'Log in → open your application → respond to EDS by uploading the requested documents.',
        'typical_days': 3,
    },
    'Resubmitted': {
        'label':   'Resubmitted',
        'icon':    '📩',
        'desc':    'You have responded to the EDS. The Scrutiny Officer is reviewing your updated documents.',
        'action':  'No action needed. Officer will verify your resubmission.',
        'typical_days': 4,
    },
    'Referred': {
        'label':   'Referred to EAC',
        'icon':    '🏛️',
        'desc':    'Application has been referred to the Expert Appraisal Committee (EAC) for deliberation.',
        'action':  'No action needed. A meeting will be scheduled. You will be notified.',
        'typical_days': 10,
    },
    'MoMGenerated': {
        'label':   'MoM Generated',
        'icon':    '📋',
        'desc':    'Minutes of the EAC Meeting have been generated. A final decision is imminent.',
        'action':  'No action needed. Await the final decision.',
        'typical_days': 3,
    },
    'Finalized': {
        'label':   'Finalized',
        'icon':    '✅',
        'desc':    'A final decision has been issued on your Environmental Clearance application.',
        'action':  'Open the Case File to view and download your clearance letter.',
        'typical_days': 0,
    },
}

# Ordered pipeline for ETA calculation
PIPELINE = [
    'Draft', 'Submitted', 'AIScreening', 'Scrutiny',
    'EDS', 'Resubmitted', 'Referred', 'MoMGenerated', 'Finalized'
]


# ── KNOWLEDGE BASE ─────────────────────────────────────────────────────────────
KB = [
    # ── Process overview ──────────────────────────────────────────────────────
    {
        'keywords': ['process', 'how does', 'how do i', 'steps', 'procedure',
                     'workflow', 'clearance process', 'ec process', 'how it works'],
        'reply': (
            "📋 *Environmental Clearance Process — PARIVESH 3.0*\n\n"
            "1. 📝 **Draft** — Create your application & upload all documents\n"
            "2. 📬 **Submit** — Submit triggers automatic AI pre-screening\n"
            "3. 🤖 **AI Screening** — System checks document completeness & validity\n"
            "4. 🔍 **Scrutiny** — Scrutiny Officer reviews your application\n"
            "5. 🔴 **EDS** — If documents are missing, EDS is raised (you must respond)\n"
            "6. 📩 **Resubmitted** — After your EDS response, officer re-reviews\n"
            "7. 🏛️ **Referred** — Application referred to Expert Appraisal Committee\n"
            "8. 📋 **MoM Generated** — Minutes of Meeting recorded after EAC discussion\n"
            "9. ✅ **Finalized** — Environmental Clearance granted or rejected\n\n"
            "Typical total time: **15–45 working days** depending on category and documents."
        )
    },

    # ── EDS ────────────────────────────────────────────────────────────────────
    {
        'keywords': ['eds', 'environmental data shortfall', 'data shortfall',
                     'shortfall', 'missing document', 'document missing', 'eds raised'],
        'reply': (
            "🔴 *EDS — Environmental Data Shortfall*\n\n"
            "EDS is raised by the Scrutiny Officer when one or more required documents "
            "are absent, incomplete, or incorrect.\n\n"
            "**What happens:**\n"
            "• You receive an email and portal notification\n"
            "• The Case File shows the exact issue and requested document\n"
            "• Status changes to 🔴 EDS\n\n"
            "**What you must do:**\n"
            "1. Open your application on the Case File page\n"
            "2. Read the EDS issue description carefully\n"
            "3. Upload the corrected / additional document\n"
            "4. Add a response message explaining your submission\n"
            "5. Click **Submit EDS Response**\n\n"
            "Status will move to 📩 Resubmitted and the officer will re-review."
        )
    },

    # ── MoM ────────────────────────────────────────────────────────────────────
    {
        'keywords': ['mom', 'mом', 'minutes', 'minutes of meeting', 'meeting minutes',
                     'eac meeting', 'expert appraisal', 'committee meeting'],
        'reply': (
            "📋 *MoM — Minutes of Meeting*\n\n"
            "After the Scrutiny Officer refers your application to the "
            "Expert Appraisal Committee (EAC), the MoM Secretariat:\n\n"
            "1. Schedules an EAC meeting (you are notified by email)\n"
            "2. Prepares an AI-generated **Gist document** summarising your application\n"
            "3. Conducts the EAC deliberation meeting\n"
            "4. Records the **Minutes of Meeting (MoM)** with the committee's recommendations\n"
            "5. Issues the final Environmental Clearance decision\n\n"
            "**Typical MoM stage duration:** 2–5 working days after referral."
        )
    },

    # ── AI screening ──────────────────────────────────────────────────────────
    {
        'keywords': ['ai', 'ai screen', 'ai pre', 'pre-screen', 'pre screen',
                     'artificial intelligence', 'automated check', 'ai score',
                     'screening', 'auto check'],
        'reply': (
            "🤖 *AI Pre-Screening — How It Works*\n\n"
            "When you submit your application, the AI engine runs **7 automatic checks**:\n\n"
            "✅ Mandatory documents present (sector-specific)\n"
            "✅ Affidavit uploaded\n"
            "✅ All file types are valid (PDF / DOCX / XLSX only)\n"
            "✅ Project details are complete (description, capacity, area)\n"
            "✅ Environmental Management Plan (EMP) found\n"
            "✅ Processing fee document present\n"
            "✅ No oversized files\n\n"
            "**Score:** 0–100% based on checks passed.\n"
            "• **100% (no issues)** → Forwarded to Scrutiny queue ✅\n"
            "• **Any issues found** → EDS raised automatically ❌\n\n"
            "The AI report is visible on your Case File page."
        )
    },

    # ── Documents ─────────────────────────────────────────────────────────────
    {
        'keywords': ['document', 'documents required', 'what documents',
                     'checklist', 'required docs', 'mandatory', 'upload what',
                     'what to upload', 'files needed', 'file required'],
        'reply': (
            "📎 *Required Documents by Sector*\n\n"
            "Documents vary by sector. Select your sector in the New Application form "
            "to see the exact checklist. Common mandatory documents include:\n\n"
            "🔹 **Processing Fee Receipt / Challan**\n"
            "🔹 **Pre-Feasibility Report**\n"
            "🔹 **Environmental Management Plan (EMP)**\n"
            "🔹 **Affidavit** (signed, confirming compliance)\n"
            "🔹 **Land Documents / Lease Agreement**\n"
            "🔹 **Forest NOC** (if applicable)\n"
            "🔹 **KML / Survey Map** (for mining sectors)\n"
            "🔹 **District Survey Report** (Sand / Limestone mining)\n"
            "🔹 **Gram Panchayat NOC** (for local-area projects)\n\n"
            "📌 **File types accepted:** PDF, DOCX, XLSX only | Max 20 MB per file\n"
            "💡 Tip: Upload all documents before submitting to pass AI screening."
        )
    },

    # ── Affidavit ─────────────────────────────────────────────────────────────
    {
        'keywords': ['affidavit', 'sworn', 'declaration', 'notary', 'notarized',
                     'compliance certificate', 'self declaration'],
        'reply': (
            "📜 *Affidavit Requirements*\n\n"
            "All applicants must upload at least **one signed affidavit** confirming "
            "compliance with environmental laws.\n\n"
            "**Available affidavit types:**\n"
            "1. Affidavit – Environmental Compliance\n"
            "2. Affidavit – Mining Safety\n"
            "3. Affidavit – CRZ (Coastal) Compliance\n"
            "4. Affidavit – Supreme Court Guidelines\n"
            "5. Affidavit – Plantation Commitment\n"
            "6. Affidavit – Pollution Control\n\n"
            "**Steps:**\n"
            "1. Print, fill, and get the affidavit **notarized** before a Notary Public\n"
            "2. Scan to PDF\n"
            "3. Upload in Step 3 (Affidavits) of the application form\n\n"
            "⚠️ Missing affidavit causes AI screening to fail."
        )
    },

    # ── Sectors ───────────────────────────────────────────────────────────────
    {
        'keywords': ['sector', 'sectors', 'sand', 'limestone', 'brick', 'infrastructure',
                     'industry', 'energy', 'coastal', 'mining sector', 'project type'],
        'reply': (
            "🏭 *Supported Project Sectors*\n\n"
            "PARIVESH 3.0 supports these sectors, each with a predefined document checklist:\n\n"
            "⛏️ **Sand Mining** — River-bed sand extraction\n"
            "🪨 **Limestone Mining** — Quarry / open-cast mining\n"
            "🧱 **Brick Kiln** — Clay brick manufacturing\n"
            "🏗️ **Infrastructure** — Roads, highways, bridges\n"
            "🏭 **Industry** — Manufacturing plants\n"
            "⚡ **Energy** — Solar, wind, thermal power\n"
            "🌊 **Coastal** — CRZ / coastal development\n"
            "📁 **Other** — Any project not in above categories\n\n"
            "Select your sector in the New Application form to auto-load the mandatory checklist."
        )
    },

    # ── Category ──────────────────────────────────────────────────────────────
    {
        'keywords': ['category a', 'category b', 'category b1', 'category b2',
                     'which category', 'cat a', 'cat b', 'what category'],
        'reply': (
            "📊 *Project Categories — EIA Notification 2006*\n\n"
            "**Category A** — Appraised at Central level (MoEFCC, New Delhi)\n"
            "• Large-scale projects with significant environmental impact\n"
            "• Examples: Thermal power ≥25 MW, mining ≥50 ha, major highways\n\n"
            "**Category B1** — State-level appraisal, requires full EIA\n"
            "• Medium-scale projects with moderate impact\n\n"
            "**Category B2** — State-level appraisal, no EIA required\n"
            "• Small-scale, lower-impact projects\n\n"
            "💡 Your project category is determined by the State/Central authority "
            "based on project scale, location, and type."
        )
    },

    # ── Status / tracking ─────────────────────────────────────────────────────
    {
        'keywords': ['status', 'where is my', 'my application', 'application status',
                     'track', 'tracking', 'where is my file', 'my file', 'application id',
                     'where my', 'what stage', 'my case', 'progress'],
        'intent':   'status',
        'reply':    '__STATUS__'   # filled dynamically
    },

    # ── Days / time spent ─────────────────────────────────────────────────────
    {
        'keywords': ['how many days', 'how long', 'days spent', 'time spent',
                     'processing time', 'days processing', 'how much time',
                     'pending since', 'pending for', 'days pending'],
        'intent':   'days',
        'reply':    '__DAYS__'
    },

    # ── ETA / estimated completion ────────────────────────────────────────────
    {
        'keywords': ['when will', 'estimated', 'estimate', 'completion',
                     'how long more', 'when approved', 'when will i get',
                     'expected time', 'when done', 'finish', 'eta'],
        'intent':   'eta',
        'reply':    '__ETA__'
    },

    # ── Latest update ─────────────────────────────────────────────────────────
    {
        'keywords': ['latest update', 'last update', 'recent update', 'latest event',
                     'what happened', 'what is the latest', 'last activity',
                     'any update', 'recent activity'],
        'intent':   'latest',
        'reply':    '__LATEST__'
    },

    # ── Officer ───────────────────────────────────────────────────────────────
    {
        'keywords': ['officer', 'who is handling', 'assigned', 'scrutiny officer',
                     'mom officer', 'who is reviewing', 'contact officer',
                     'handler', 'who has my file'],
        'intent':   'officer',
        'reply':    '__OFFICER__'
    },

    # ── Documents uploaded ────────────────────────────────────────────────────
    {
        'keywords': ['documents uploaded', 'uploaded documents', 'my documents',
                     'what have i uploaded', 'documents submitted', 'files uploaded'],
        'intent':   'uploaded_docs',
        'reply':    '__DOCS__'
    },

    # ── Submit how-to ─────────────────────────────────────────────────────────
    {
        'keywords': ['how to submit', 'how do i submit', 'submit application',
                     'how to apply', 'start application', 'new application',
                     'how to create', 'create application'],
        'reply': (
            "🚀 *How to Submit Your Application*\n\n"
            "**Step 1 — Create Application**\n"
            "Go to Dashboard → click ➕ New Application\n\n"
            "**Step 2 — Project Details**\n"
            "Fill in: Project Name, Sector, Category, Location, Capacity, Area\n\n"
            "**Step 3 — Upload Documents**\n"
            "Upload all mandatory documents shown in the sector checklist\n\n"
            "**Step 4 — Affidavit**\n"
            "Upload your signed, notarized affidavit\n\n"
            "**Step 5 — Review & Submit**\n"
            "Accept the declaration → click 🚀 Submit & Run AI Screen\n\n"
            "✅ AI pre-screening runs instantly. You'll be notified of the result."
        )
    },

    # ── Notifications ─────────────────────────────────────────────────────────
    {
        'keywords': ['notification', 'email', 'notify', 'alert', 'notified',
                     'will i get email', 'inform me', 'sms', 'message'],
        'reply': (
            "🔔 *Email Notifications*\n\n"
            "You receive automatic emails for every major event:\n\n"
            "📧 AI Pre-Screen **Passed** — application in Scrutiny queue\n"
            "📧 AI Pre-Screen **Failed** — with issue list and fix instructions\n"
            "📧 **EDS Raised** — issue description + requested document\n"
            "📧 **Scrutiny Officer Assigned** — officer name, dept, email, phone\n"
            "📧 **MoM Officer Assigned** — officer contact details\n"
            "📧 **Application Referred** to EAC meeting\n"
            "📧 **Meeting Scheduled** — date and agenda\n"
            "📧 **MoM Generated** — minutes ready for review\n"
            "📧 **Final Decision** — Granted / Rejected with remarks\n\n"
            "Also check the 🔔 bell icon in the portal for in-app notifications."
        )
    },

    # ── Download ──────────────────────────────────────────────────────────────
    {
        'keywords': ['download', 'get document', 'download document', 'download file',
                     'access document', 'retrieve file'],
        'reply': (
            "⬇️ *Downloading Documents*\n\n"
            "All uploaded documents are securely stored and protected.\n\n"
            "**To download:**\n"
            "1. Log in → go to Dashboard\n"
            "2. Click 📂 Open on your application\n"
            "3. Scroll to *All Documents* panel on the right\n"
            "4. Click the ↓ download button next to any document\n\n"
            "Each document version is preserved separately — you can download "
            "any previous version from the timeline."
        )
    },

    # ── Timeline ──────────────────────────────────────────────────────────────
    {
        'keywords': ['timeline', 'history', 'case file', 'activity log',
                     'audit trail', 'events', 'what happened to my'],
        'reply': (
            "📜 *Application Timeline & Case File*\n\n"
            "Every action on your application is logged in the **Case File Timeline**:\n\n"
            "🤖 AI screening results with score\n"
            "📬 Submission events\n"
            "🔍 Scrutiny officer assignments and verifications\n"
            "🔴 EDS issues raised (with description)\n"
            "📩 Your EDS responses with document versions\n"
            "🏛️ EAC referral and meeting events\n"
            "📋 MoM generation\n"
            "⚖️ Final decision\n\n"
            "**Access:** Dashboard → click 📂 Open on any application."
        )
    },

    # ── Contact / help ────────────────────────────────────────────────────────
    {
        'keywords': ['contact', 'helpdesk', 'help', 'support', 'phone number',
                     'email address', 'reach', 'get help'],
        'reply': (
            "📞 *Contact & Support*\n\n"
            "**PARIVESH Portal Helpdesk**\n"
            "📧 help@parivesh.gov.in\n"
            "📞 1800-XXX-XXXX (Toll Free, Mon–Fri 10am–5pm)\n\n"
            "**Ministry of Environment, Forest & Climate Change**\n"
            "Indira Paryavaran Bhawan, Jor Bagh Road\n"
            "New Delhi – 110003\n\n"
            "For Scrutiny Officer contact, open your Case File — the officer's "
            "name, email and phone are shown in the Officer Panel."
        )
    },
]


# ── PariveshChatbot CLASS ──────────────────────────────────────────────────────
class PariveshChatbot:
    """
    Plug-and-play chatbot for PARIVESH 3.0 Environmental Clearance Portal.

    Usage:
        bot = PariveshChatbot()
        reply = bot.reply("what is my application status", user_id=3)
    """

    # Suggested quick-action buttons sent on greeting / fallback
    QUICK_SUGGESTIONS = [
        "What is my application status?",
        "What documents do I need?",
        "What does EDS mean?",
        "How does the clearance process work?",
        "When will my application be approved?",
        "What is the latest update?",
    ]

    # ── DB helpers ────────────────────────────────────────────────────────────

    def get_application(self, user_id: int):
        """Return the most recent application for this user."""
        apps = db.list_applications(user_id=user_id, role='PP')
        if not apps:
            return None
        # Sort by created_at descending, return latest
        apps.sort(key=lambda a: a.get('created_at', ''), reverse=True)
        return apps[0]

    def get_application_by_id(self, app_id: str):
        """Return a specific application by ID."""
        return db.get_application(app_id)

    def get_latest_timeline(self, application_id: str):
        """Return the most recent timeline event."""
        events = db.get_timeline(application_id)
        if not events:
            return None
        return events[-1]   # already ordered ASC, so last = most recent

    def get_documents(self, application_id: str):
        """Return list of uploaded documents."""
        return db.get_documents_for_app(application_id)

    def calculate_days(self, application: dict) -> int:
        """Return number of calendar days since application was created."""
        created_raw = application.get('created_at', '')
        if not created_raw:
            return 0
        try:
            # Handle both ISO format with and without timezone
            created_raw = created_raw.split('.')[0]  # strip microseconds
            created = datetime.strptime(created_raw, '%Y-%m-%dT%H:%M:%S')
        except ValueError:
            try:
                created = datetime.strptime(created_raw, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return 0
        now = datetime.utcnow()
        return max(0, (now - created).days)

    def estimate_completion(self, application: dict) -> str:
        """Estimate remaining days based on current stage and remaining pipeline stages."""
        status = application.get('status', 'Draft')
        if status == 'Finalized':
            return "Your application has already been finalized. Check the Case File for the decision."

        try:
            current_idx = PIPELINE.index(status)
        except ValueError:
            return "Unable to estimate — unknown status."

        remaining_stages = PIPELINE[current_idx:]
        remaining_days = sum(STAGE_INFO.get(s, {}).get('typical_days', 2) for s in remaining_stages)

        if remaining_days == 0:
            return "Your application is at the final stage. A decision is imminent."
        elif remaining_days <= 5:
            return f"Estimated remaining time: approximately **{remaining_days}–{remaining_days + 3} working days**."
        else:
            lo = remaining_days
            hi = remaining_days + 10
            return f"Estimated remaining time: approximately **{lo}–{hi} working days**, depending on document verification and committee availability."

    # ── Intent matching ───────────────────────────────────────────────────────

    def _match_intent(self, message: str):
        """
        Score each KB entry by counting keyword matches.
        Longer keywords score higher (more specific = more reliable).
        Returns the best-matching KB entry (or None).
        """
        msg = message.lower().strip()
        best_entry = None
        best_score = 0.0

        for entry in KB:
            score = 0.0
            for kw in entry['keywords']:
                if kw in msg:
                    # Longer keyword = higher weight (more specific)
                    score += 1.0 + (len(kw) / 20.0)
            if score > best_score:
                best_score = score
                best_entry = entry

        return best_entry if best_score > 0 else None

    def _extract_app_id(self, message: str):
        """Try to extract an application ID like EC-XXXXXXXX from the message."""
        match = re.search(r'EC-[A-Z0-9]{6,10}', message.upper())
        return match.group(0) if match else None

    # ── Dynamic replies ───────────────────────────────────────────────────────

    def _reply_status(self, app, user_id: int) -> str:
        if not app:
            return (
                "I couldn't find an active application for your account.\n\n"
                "If you've just registered, go to **Dashboard → ➕ New Application** "
                "to start your first application."
            )
        status = app.get('status', 'Unknown')
        info   = STAGE_INFO.get(status, {})
        days   = self.calculate_days(app)
        officer = app.get('officer_name') or app.get('mom_officer_name')
        officer_line = f"\n👤 **Current Handler:** {officer}" if officer else ""

        return (
            f"{info.get('icon','📁')} *Application Status — {app['id']}*\n\n"
            f"**Project:** {app.get('project_name', '–')}\n"
            f"**Status:** {info.get('label', status)}\n"
            f"**In process for:** {days} day{'s' if days != 1 else ''}\n"
            f"{officer_line}\n\n"
            f"ℹ️ {info.get('desc', '')}\n\n"
            f"**Next step:** {info.get('action', 'Check your Case File for details.')}"
        )

    def _reply_days(self, app) -> str:
        if not app:
            return "I couldn't find an active application to calculate processing time."
        days = self.calculate_days(app)
        status = app.get('status', '')
        if days == 0:
            return f"Your application **{app['id']}** was submitted today. Processing has just begun."
        return (
            f"⏱️ Your application **{app['id']}** ({app.get('project_name','')}) "
            f"has been in process for **{days} day{'s' if days != 1 else ''}**.\n\n"
            f"Current stage: {STAGE_INFO.get(status, {}).get('label', status)}"
        )

    def _reply_eta(self, app) -> str:
        if not app:
            return "I couldn't find an active application to estimate completion time."
        eta = self.estimate_completion(app)
        days = self.calculate_days(app)
        return (
            f"📅 *Estimated Completion — {app['id']}*\n\n"
            f"Current stage: **{STAGE_INFO.get(app.get('status',''), {}).get('label', app.get('status',''))}**\n"
            f"Days in process: **{days}**\n\n"
            f"{eta}\n\n"
            f"💡 Tip: Respond to any EDS quickly to avoid delays."
        )

    def _reply_latest(self, app) -> str:
        if not app:
            return "I couldn't find an active application to show the latest update."
        event = self.get_latest_timeline(app['id'])
        if not event:
            return f"No timeline events found for application **{app['id']}** yet."
        icon = {
            'submission': '📬', 'ai_screen': '🤖', 'issue': '🔴',
            'response': '📩', 'file_upload': '📎', 'file_update': '🔄',
            'verification': '🔍', 'meeting': '🏛️', 'decision': '⚖️'
        }.get(event.get('event_type', ''), '📌')

        dt_raw = event.get('datetime', '')[:16].replace('T', ' ')
        actor  = event.get('actor_name', 'System')
        dept   = event.get('department', '')
        msg    = event.get('message', '')[:200]

        return (
            f"{icon} *Latest Update — {app['id']}*\n\n"
            f"🕐 **Date/Time:** {dt_raw}\n"
            f"👤 **By:** {actor}" + (f" ({dept})" if dept else "") + "\n"
            f"📌 **Event:** {event.get('event_type','')}\n\n"
            f"_{msg}_"
        )

    def _reply_officer(self, app) -> str:
        if not app:
            return "I couldn't find an active application to check the assigned officer."
        scrutiny_name  = app.get('officer_name')
        scrutiny_dept  = app.get('officer_dept', '')
        scrutiny_email = app.get('officer_email', '')
        scrutiny_phone = app.get('officer_phone', '')
        mom_name  = app.get('mom_officer_name')
        mom_dept  = app.get('mom_officer_dept', '')
        mom_email = app.get('mom_officer_email', '')
        mom_phone = app.get('mom_officer_phone', '')

        lines = [f"👤 *Officer Assignment — {app['id']}*\n"]

        if scrutiny_name:
            lines.append("**Scrutiny Officer:**")
            lines.append(f"  📛 {scrutiny_name}")
            if scrutiny_dept:  lines.append(f"  🏢 {scrutiny_dept}")
            if scrutiny_email: lines.append(f"  ✉️  {scrutiny_email}")
            if scrutiny_phone: lines.append(f"  📞 {scrutiny_phone}")
        else:
            lines.append("**Scrutiny Officer:** Not yet assigned")

        if ['Referred','MoMGenerated','Finalized'].__contains__(app.get('status','')):
            lines.append("")
            if mom_name:
                lines.append("**MoM Secretariat Officer:**")
                lines.append(f"  📛 {mom_name}")
                if mom_dept:  lines.append(f"  🏢 {mom_dept}")
                if mom_email: lines.append(f"  ✉️  {mom_email}")
                if mom_phone: lines.append(f"  📞 {mom_phone}")
            else:
                lines.append("**MoM Officer:** Not yet assigned")

        return '\n'.join(lines)

    def _reply_docs(self, app) -> str:
        if not app:
            return "I couldn't find an active application to list documents."
        docs = self.get_documents(app['id'])
        if not docs:
            return f"No documents uploaded yet for application **{app['id']}**."
        lines = [f"📎 *Uploaded Documents — {app['id']}*\n", f"Total: **{len(docs)} file(s)**\n"]
        for d in docs[:10]:   # cap at 10
            aff = " 📜 (Affidavit)" if d.get('is_affidavit') else ""
            lines.append(f"• v{d['version']} — {d['document_type']}: _{d['original_name']}_{aff}")
        if len(docs) > 10:
            lines.append(f"... and {len(docs)-10} more. Open Case File for full list.")
        return '\n'.join(lines)

    # ── Greeting ──────────────────────────────────────────────────────────────

    def _greeting(self) -> str:
        suggestions = '\n'.join(f"• {s}" for s in self.QUICK_SUGGESTIONS)
        return (
            "👋 *Hello! I'm the PARIVESH Assistant.*\n\n"
            "I can help you with:\n\n"
            f"{suggestions}\n\n"
            "Just type your question — I understand natural language!"
        )

    def _fallback(self) -> str:
        suggestions = " | ".join(f'"{s}"' for s in self.QUICK_SUGGESTIONS[:3])
        return (
            "🤔 I didn't quite understand that. I can help with:\n\n"
            "• Application status & tracking\n"
            "• Required documents & checklists\n"
            "• EDS, MoM, AI screening explanations\n"
            "• Processing time & estimated completion\n"
            "• Latest timeline update\n"
            "• Officer contact details\n\n"
            f"Try asking: {suggestions}"
        )

    # ── Main reply entry point ────────────────────────────────────────────────

    def reply(self, message: str, user_id: int = None, app_id_hint: str = None) -> str:
        """
        Process a user message and return a reply string.

        Args:
            message:     Raw user message text
            user_id:     Logged-in user's DB ID (for live data lookups)
            app_id_hint: Optional explicit application ID from URL context
        """
        msg = (message or '').strip()
        if not msg:
            return "Please type your question."

        # Greeting detection
        greetings = {'hi', 'hello', 'hey', 'hii', 'help', 'start', 'namaste'}
        if msg.lower() in greetings or len(msg) <= 3:
            return self._greeting()

        # Try to find application (use hint, then extract from message, then latest for user)
        def _get_app():
            if app_id_hint:
                return self.get_application_by_id(app_id_hint)
            extracted = self._extract_app_id(msg)
            if extracted:
                return self.get_application_by_id(extracted)
            if user_id:
                return self.get_application(user_id)
            return None

        # Match intent
        entry = self._match_intent(msg)

        if entry is None:
            return self._fallback()

        intent = entry.get('intent')

        # Static reply — no DB needed
        if not intent:
            return entry['reply']

        # Dynamic replies — need live application data
        app = _get_app()

        if intent == 'status':
            return self._reply_status(app, user_id)
        elif intent == 'days':
            return self._reply_days(app)
        elif intent == 'eta':
            return self._reply_eta(app)
        elif intent == 'latest':
            return self._reply_latest(app)
        elif intent == 'officer':
            return self._reply_officer(app)
        elif intent == 'uploaded_docs':
            return self._reply_docs(app)

        return self._fallback()
