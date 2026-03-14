"""
email_service.py — SMTP email notifications for PARIVESH 3.0
Uses Python stdlib smtplib only. No third-party libraries required.

Configure in .env:
  EMAIL_ENABLED=true              # set false to disable during dev
  SMTP_HOST=smtp.gmail.com        # or smtp.office365.com etc.
  SMTP_PORT=587
  SMTP_USER=your@gmail.com        # sender address (Gmail: use App Password)
  SMTP_PASS=your-app-password     # Gmail: Settings → Security → App Passwords
  EMAIL_FROM_NAME=PARIVESH 3.0 Portal
  APP_URL=http://localhost:5000   # base URL for case file links in emails
"""
import os, smtplib, threading, logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

log = logging.getLogger('parivesh.email')

ENABLED       = os.environ.get('EMAIL_ENABLED', 'true').lower() == 'true'
SMTP_HOST     = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT     = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USER     = os.environ.get('SMTP_USER', '')
SMTP_PASS     = os.environ.get('SMTP_PASS', '')
FROM_NAME     = os.environ.get('EMAIL_FROM_NAME', 'PARIVESH 3.0 Portal')
APP_URL       = os.environ.get('APP_URL', 'http://localhost:5000')


# ── HTML WRAPPER ──────────────────────────────────────────────────────────────
def _wrap(subject, body_html):
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>
  body{{font-family:Arial,sans-serif;background:#F4F6F9;margin:0;padding:0;}}
  .w{{max-width:600px;margin:28px auto;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.1);}}
  .hd{{background:#06294A;padding:18px 26px;}}
  .hd-t{{color:#fff;font-size:18px;font-weight:700;letter-spacing:.4px;}}
  .hd-s{{color:rgba(255,255,255,.6);font-size:11px;margin-top:2px;}}
  .stripe{{height:4px;background:linear-gradient(90deg,#FF9933 33%,#fff 33%,#fff 66%,#138808 66%);}}
  .bd{{padding:26px;}}
  .bd h2{{color:#0A3D62;font-size:16px;margin:0 0 14px;}}
  .bd p{{color:#333;line-height:1.7;font-size:13.5px;margin:0 0 11px;}}
  .box{{background:#EEF2F7;border-left:4px solid #1565C0;border-radius:0 6px 6px 0;padding:12px 16px;margin:14px 0;}}
  .row{{font-size:13px;margin-bottom:5px;color:#333;}}
  .row b{{color:#0A3D62;display:inline-block;min-width:150px;}}
  .officer-box{{background:#E8F5E9;border-left:4px solid #2E7D32;border-radius:0 6px 6px 0;padding:12px 16px;margin:14px 0;}}
  .btn{{display:inline-block;background:#0A3D62;color:#fff!important;padding:10px 22px;border-radius:6px;text-decoration:none;font-weight:700;font-size:13px;margin:14px 0;}}
  .ft{{background:#EEF2F7;padding:12px 26px;font-size:11px;color:#888;border-top:1px solid #ddd;}}
</style></head><body>
<div class="w">
  <div class="hd"><div class="hd-t">🌿 PARIVESH 3.0</div>
  <div class="hd-s">Environmental Clearance Management System — MoEF&CC, Govt. of India</div></div>
  <div class="stripe"></div>
  <div class="bd"><h2>{subject}</h2>{body_html}</div>
  <div class="ft">This is an automated message from PARIVESH 3.0. Do not reply.<br>
  © Ministry of Environment, Forest &amp; Climate Change, Government of India</div>
</div></body></html>"""


# ── SEND (background thread) ──────────────────────────────────────────────────
def _send(to, subject, html):
    if not to or '@' not in to:
        log.debug(f"Email skipped — invalid address: {to!r}"); return
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From']    = f"{FROM_NAME} <{SMTP_USER}>"
        msg['To']      = to
        msg.attach(MIMEText(html, 'html'))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.ehlo(); s.starttls(); s.ehlo()
            if SMTP_USER and SMTP_PASS:
                s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_USER, to, msg.as_string())
        log.info(f"Email sent → {to}: {subject}")
    except Exception as e:
        log.error(f"Email failed → {to}: {e}")


def _queue(to, subject, html):
    """Fire-and-forget in a daemon thread — never blocks the HTTP response."""
    if not ENABLED:
        log.debug(f"Email disabled. Would send '{subject}' → {to}"); return
    threading.Thread(target=_send, args=(to, subject, html), daemon=True).start()


def _case_btn(app_id):
    return f'<a href="{APP_URL}/case_file?id={app_id}" class="btn">→ Open Case File: {app_id}</a>'

def _officer_card(name, dept, email, phone):
    rows = f'<div class="row"><b>Officer Name:</b> {name}</div>'
    if dept:  rows += f'<div class="row"><b>Department:</b> {dept}</div>'
    if email: rows += f'<div class="row"><b>Email:</b> <a href="mailto:{email}">{email}</a></div>'
    if phone: rows += f'<div class="row"><b>Phone / Mobile:</b> {phone}</div>'
    return f'<div class="officer-box">{rows}</div>'


# ── PUBLIC EMAIL FUNCTIONS ────────────────────────────────────────────────────

def notify_ai_passed(to, name, app_id, score):
    subj = f"[PARIVESH] AI Pre-Screen Passed — {app_id} — Now in Scrutiny Queue"
    body = f"""<p>Dear {name},</p>
    <p>Your application has <b>passed the AI Pre-Screening</b> and is now in the Scrutiny queue for review.</p>
    <div class="box">
      <div class="row"><b>Application ID:</b> {app_id}</div>
      <div class="row"><b>AI Score:</b> {score}%</div>
      <div class="row"><b>Current Status:</b> Scrutiny</div>
    </div>
    <p>You will be notified once a Scrutiny Officer is assigned and reviews your application.</p>
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))


def notify_ai_failed(to, name, app_id, score, issues):
    subj = f"[PARIVESH] AI Pre-Screen Failed — {app_id} — Action Required"
    iss_html = ''.join(
        f'<div class="row" style="color:#C62828">❌ <b>{i["category"]}:</b> {", ".join(i.get("items",[]))}</div>'
        for i in issues
    )
    body = f"""<p>Dear {name},</p>
    <p>Your application <b>did not pass the AI Pre-Screening</b> due to the issues listed below. Please fix them and resubmit.</p>
    <div class="box" style="border-color:#C62828;background:#FFF8F8;">
      <div class="row"><b>Application ID:</b> {app_id}</div>
      <div class="row"><b>AI Score:</b> {score}% (issues found)</div>
      <br>{iss_html}
    </div>
    <p>Log in, open your application, upload the missing documents, and resubmit.</p>
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))


def notify_scrutiny_assigned(to, name, app_id, officer_name, officer_dept, officer_email, officer_phone):
    subj = f"[PARIVESH] Scrutiny Officer Assigned — {app_id}"
    body = f"""<p>Dear {name},</p>
    <p>A <b>Scrutiny Officer</b> has been assigned to review your application.</p>
    <div class="box">
      <div class="row"><b>Application ID:</b> {app_id}</div>
    </div>
    <p><b>Assigned Officer Details:</b></p>
    {_officer_card(officer_name, officer_dept, officer_email, officer_phone)}
    <p>The officer will review your documents and may raise an EDS (Environmental Data Shortfall) if any information is missing. You will be notified accordingly.</p>
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))


def notify_scrutiny_unassigned(to, name, app_id, prev_officer):
    subj = f"[PARIVESH] Scrutiny Officer Unassigned — {app_id}"
    body = f"""<p>Dear {name},</p>
    <p>The Scrutiny Officer <b>{prev_officer}</b> has been unassigned from your application. A new Scrutiny Officer will be assigned shortly.</p>
    <div class="box">
      <div class="row"><b>Application ID:</b> {app_id}</div>
      <div class="row"><b>Previous Officer:</b> {prev_officer}</div>
      <div class="row"><b>Action Required:</b> None — please wait for reassignment</div>
    </div>
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))


def notify_eds_raised(to, name, app_id, issue, req_doc=''):
    subj = f"[PARIVESH] EDS Raised — {app_id} — Action Required"
    req = f'<div class="row"><b>Requested Document:</b> {req_doc}</div>' if req_doc else ''
    body = f"""<p>Dear {name},</p>
    <p>The Scrutiny Officer has raised an <b>Environmental Data Shortfall (EDS)</b> on your application. Please upload the required documents and resubmit.</p>
    <div class="box" style="border-color:#E65100;background:#FFF8F0;">
      <div class="row"><b>Application ID:</b> {app_id}</div>
      <div class="row"><b>Issue Raised:</b> {issue}</div>
      {req}
    </div>
    <p>Log in, open your application, and submit your response with corrected or additional documents.</p>
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))


def notify_referred(to, name, app_id):
    subj = f"[PARIVESH] Application Referred to EAC — {app_id}"
    body = f"""<p>Dear {name},</p>
    <p>Your application has been <b>referred to the Expert Appraisal Committee (EAC)</b> for deliberation. This is a major milestone in the clearance process.</p>
    <div class="box">
      <div class="row"><b>Application ID:</b> {app_id}</div>
      <div class="row"><b>Status:</b> Referred to EAC</div>
    </div>
    <p>The MoM Secretariat will schedule an EAC meeting and generate the Minutes of Meeting. You will be notified of the outcome.</p>
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))


def notify_mom_assigned(to, name, app_id, officer_name, officer_dept, officer_email, officer_phone):
    subj = f"[PARIVESH] MoM Secretariat Officer Assigned — {app_id}"
    body = f"""<p>Dear {name},</p>
    <p>A <b>MoM Secretariat Officer</b> has been assigned to your application for the EAC meeting and Minutes of Meeting preparation.</p>
    <div class="box">
      <div class="row"><b>Application ID:</b> {app_id}</div>
    </div>
    <p><b>Assigned MoM Officer Details:</b></p>
    {_officer_card(officer_name, officer_dept, officer_email, officer_phone)}
    <p>An EAC meeting will be scheduled. You will be notified once the meeting date is set and when the MoM is generated.</p>
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))


def notify_mom_unassigned(to, name, app_id, prev_officer):
    subj = f"[PARIVESH] MoM Officer Unassigned — {app_id}"
    body = f"""<p>Dear {name},</p>
    <p>The MoM Secretariat Officer <b>{prev_officer}</b> has been unassigned from your application. A new officer will be assigned shortly.</p>
    <div class="box">
      <div class="row"><b>Application ID:</b> {app_id}</div>
      <div class="row"><b>Previous MoM Officer:</b> {prev_officer}</div>
    </div>
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))


def notify_meeting_scheduled(to, name, app_id, meeting_title, meeting_date):
    subj = f"[PARIVESH] EAC Meeting Scheduled — {app_id} — {meeting_date}"
    body = f"""<p>Dear {name},</p>
    <p>An <b>Expert Appraisal Committee (EAC) meeting</b> has been scheduled for your application.</p>
    <div class="box">
      <div class="row"><b>Application ID:</b> {app_id}</div>
      <div class="row"><b>Meeting:</b> {meeting_title}</div>
      <div class="row"><b>Scheduled Date:</b> {meeting_date}</div>
    </div>
    <p>The Committee will review your application. Minutes of Meeting (MoM) will be generated after the meeting.</p>
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))


def notify_mom_generated(to, name, app_id):
    subj = f"[PARIVESH] Minutes of Meeting Generated — {app_id}"
    body = f"""<p>Dear {name},</p>
    <p>The <b>Minutes of Meeting (MoM)</b> have been generated for your application. A final decision will be issued shortly.</p>
    <div class="box">
      <div class="row"><b>Application ID:</b> {app_id}</div>
      <div class="row"><b>Status:</b> MoM Generated</div>
    </div>
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))


def notify_final_decision(to, name, app_id, decision, remarks=''):
    granted = 'GRANTED' in decision.upper()
    subj = f"[PARIVESH] Final Decision: EC {decision} — {app_id}"
    col  = '#2E7D32' if granted else '#C62828'
    icon = '✅' if granted else '❌'
    note = ("<p>Congratulations! Please download your Environmental Clearance letter and comply with all stated conditions.</p>"
            if granted else
            "<p>Your application was not approved. You may re-apply after addressing the concerns raised.</p>")
    body = f"""<p>Dear {name},</p>
    <p>A <b>final decision</b> has been issued on your Environmental Clearance application.</p>
    <div class="box">
      <div class="row"><b>Application ID:</b> {app_id}</div>
      <div class="row"><b>Decision:</b> <span style="color:{col};font-weight:700">{icon} {decision}</span></div>
      {'<div class="row"><b>Remarks:</b> '+remarks+'</div>' if remarks else ''}
    </div>
    {note}
    {_case_btn(app_id)}"""
    _queue(to, subj, _wrap(subj, body))
