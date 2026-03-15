"""
routes/complaints.py — Complaint Management System for PARIVESH 3.0
====================================================================
Access rules:
  PP    → create complaint, view own complaints only
  Admin → view ALL complaints, respond, change status
  Scrutiny / MoM → 403 Forbidden
"""

import db
import email_service
from flask import Blueprint, request, jsonify
from routes.auth import login_required, role_required, current_user

complaint_bp = Blueprint('complaint', __name__)

VALID_STATUSES = ('Open', 'Resolved', 'Closed')


# ── PP: SUBMIT COMPLAINT ──────────────────────────────────────────────────────
@complaint_bp.route('/complaint/create', methods=['POST'])
@login_required
@role_required('PP', 'Admin')
def create_complaint():
    u    = current_user()
    data = request.get_json() or {}

    subject     = (data.get('subject', '') or '').strip()
    description = (data.get('description', '') or '').strip()
    app_id      = (data.get('application_id', '') or '').strip()

    if not subject:
        return jsonify({'error': 'Subject is required'}), 400
    if not description:
        return jsonify({'error': 'Description is required'}), 400
    if len(description) < 20:
        return jsonify({'error': 'Description must be at least 20 characters'}), 400

    # Validate app_id if provided
    if app_id:
        app = db.get_application(app_id)
        if not app:
            return jsonify({'error': f'Application {app_id} not found'}), 404
        if app['created_by'] != u['id'] and u['role'] != 'Admin':
            return jsonify({'error': 'You can only reference your own applications'}), 403

    complaint = db.create_complaint(
        user_id=u['id'],
        subject=subject,
        description=description,
        application_id=app_id
    )

    # Notify all Admin users
    admins = db.get_all_users()
    for admin in admins:
        if admin['role'] == 'Admin':
            db.create_notification(
                admin['id'], app_id or None,
                f'New Complaint #{complaint["id"]}',
                f'From: {u["name"]} | Subject: {subject}'
            )
            email_service.notify_complaint_received(
                to=admin.get('email', ''),
                admin_name=admin['name'],
                complaint_id=complaint['id'],
                user_name=u['name'],
                user_email=u.get('email', ''),
                subject=subject,
                description=description,
                app_id=app_id
            )

    db.log_audit(u['id'], 'COMPLAINT_CREATE', f'complaint:{complaint["id"]}', subject)

    return jsonify({
        'message': 'Complaint submitted successfully',
        'complaint': complaint
    }), 201


# ── PP: VIEW OWN COMPLAINTS ───────────────────────────────────────────────────
@complaint_bp.route('/complaint/user', methods=['GET'])
@login_required
@role_required('PP', 'Admin')
def user_complaints():
    u = current_user()
    # PP sees only their own; Admin passed here sees their own (use /complaint/admin for all)
    uid = u['id'] if u['role'] == 'PP' else u['id']
    return jsonify(db.get_complaints_by_user(uid))


# ── ADMIN: VIEW ALL COMPLAINTS ────────────────────────────────────────────────
@complaint_bp.route('/complaint/admin', methods=['GET'])
@login_required
@role_required('Admin')
def admin_complaints():
    status_filter = request.args.get('status', '').strip()
    all_c = db.get_all_complaints()
    if status_filter and status_filter in VALID_STATUSES:
        all_c = [c for c in all_c if c['status'] == status_filter]
    return jsonify(all_c)


# ── ADMIN: VIEW SINGLE COMPLAINT ──────────────────────────────────────────────
@complaint_bp.route('/complaint/<int:cid>', methods=['GET'])
@login_required
def get_complaint(cid):
    u = current_user()
    complaint = db.get_complaint(cid)
    if not complaint:
        return jsonify({'error': 'Complaint not found'}), 404
    # PP can only view their own
    if u['role'] == 'PP' and complaint['user_id'] != u['id']:
        return jsonify({'error': 'Forbidden'}), 403
    # Scrutiny/MoM blocked entirely
    if u['role'] in ('Scrutiny', 'MoM'):
        return jsonify({'error': 'Access denied'}), 403
    return jsonify(complaint)


# ── ADMIN: RESPOND ────────────────────────────────────────────────────────────
@complaint_bp.route('/complaint/respond', methods=['POST'])
@login_required
@role_required('Admin')
def respond_complaint():
    u    = current_user()
    data = request.get_json() or {}

    cid      = data.get('complaint_id')
    response = (data.get('response', '') or '').strip()
    status   = data.get('status', 'Resolved').strip()

    if not cid:
        return jsonify({'error': 'complaint_id required'}), 400
    if not response:
        return jsonify({'error': 'Response text is required'}), 400
    if status not in VALID_STATUSES:
        return jsonify({'error': f'Status must be one of {VALID_STATUSES}'}), 400

    complaint = db.get_complaint(int(cid))
    if not complaint:
        return jsonify({'error': 'Complaint not found'}), 404

    updated = db.respond_to_complaint(
        cid=int(cid),
        admin_id=u['id'],
        response_text=response,
        status=status
    )

    # In-app notification to the PP
    db.create_notification(
        complaint['user_id'],
        complaint.get('application_id') or None,
        f'Admin responded to your Complaint #{cid}',
        f'Status: {status} | {response[:80]}'
    )

    # Email to PP
    email_service.notify_complaint_response(
        to=complaint.get('user_email', ''),
        name=complaint.get('user_name', 'Applicant'),
        complaint_id=cid,
        subject=complaint['subject'],
        response=response,
        status=status,
        app_id=complaint.get('application_id', '')
    )

    db.log_audit(u['id'], 'COMPLAINT_RESPOND', f'complaint:{cid}',
                 f'status={status}')

    return jsonify({
        'message': 'Response submitted',
        'complaint': updated
    })


# ── ADMIN: UPDATE STATUS ONLY ─────────────────────────────────────────────────
@complaint_bp.route('/complaint/<int:cid>/status', methods=['PATCH'])
@login_required
@role_required('Admin')
def update_complaint_status(cid):
    data   = request.get_json() or {}
    status = data.get('status', '').strip()
    if status not in VALID_STATUSES:
        return jsonify({'error': f'Status must be one of {VALID_STATUSES}'}), 400
    complaint = db.get_complaint(cid)
    if not complaint:
        return jsonify({'error': 'Not found'}), 404
    conn = db.get_conn()
    conn.execute("UPDATE complaints SET status=? WHERE id=?", (status, cid))
    conn.commit(); conn.close()
    return jsonify({'message': 'Status updated', 'complaint': db.get_complaint(cid)})
