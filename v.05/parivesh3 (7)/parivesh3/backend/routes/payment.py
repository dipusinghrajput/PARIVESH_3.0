"""
routes/payment.py — Dummy Payment Gateway for PARIVESH 3.0
===========================================================
Simulates a full payment flow:
  1. PP submits application → POST /api/payment/initiate   (creates PENDING record)
  2. PP is shown payment page with method selection
  3. PP clicks Pay Now → POST /api/payment/confirm         (marks SUCCESS)
  4. Confirmation email sent; timeline event logged
"""

import uuid, json
import db
import email_service
from flask import Blueprint, request, jsonify, session
from routes.auth import login_required, role_required, current_user

payment_bp = Blueprint('payment', __name__)

# ── Fee schedule (₹) by application category ─────────────────────────────────
CATEGORY_FEES = {
    'A':  10000,
    'B1':  5000,
    'B2':  2500,
}
DEFAULT_FEE = 5000
PAYMENT_METHODS = ['UPI', 'Net Banking', 'Debit/Credit Card', 'QR Code']


def _gen_txn_id():
    """Generate a unique demo transaction ID like DEMO_TXN_A3F7C912."""
    return 'DEMO_TXN_' + uuid.uuid4().hex[:8].upper()


# ── INITIATE PAYMENT ──────────────────────────────────────────────────────────
@payment_bp.route('/payment/initiate', methods=['POST'])
@login_required
@role_required('PP', 'Admin')
def initiate_payment():
    """
    Called right after application is created/submitted.
    Creates a PENDING payment record and returns fee details.
    """
    u = current_user()
    data = request.get_json() or {}
    app_id = data.get('application_id', '').strip()

    if not app_id:
        return jsonify({'error': 'application_id required'}), 400

    app = db.get_application(app_id)
    if not app:
        return jsonify({'error': 'Application not found'}), 404

    # Only the application owner can pay
    if app['created_by'] != u['id'] and u['role'] != 'Admin':
        return jsonify({'error': 'Forbidden'}), 403

    # Check if already paid
    existing = db.get_payment_by_app(app_id)
    if existing and existing['status'] == 'SUCCESS':
        return jsonify({
            'message': 'Payment already completed',
            'payment': existing
        })

    amount = CATEGORY_FEES.get(app.get('category', ''), DEFAULT_FEE)
    txn_id = _gen_txn_id()

    payment = db.create_payment(
        application_id=app_id,
        user_id=u['id'],
        amount=amount,
        payment_method='PENDING',   # updated at confirm step
        transaction_id=txn_id
    )

    db.log_audit(u['id'], 'PAYMENT_INITIATED', app_id, f'txn={txn_id} amount={amount}')

    return jsonify({
        'message': 'Payment initiated',
        'payment': payment,
        'fee_details': {
            'application_id': app_id,
            'project_name':   app['project_name'],
            'category':       app.get('category', ''),
            'amount':         amount,
            'transaction_id': txn_id,
            'methods':        PAYMENT_METHODS,
        }
    }), 201


# ── CONFIRM / SIMULATE PAYMENT ────────────────────────────────────────────────
@payment_bp.route('/payment/confirm', methods=['POST'])
@login_required
@role_required('PP', 'Admin')
def confirm_payment():
    """
    PP selects a payment method and clicks Pay Now.
    Simulates success, updates DB, fires email, logs timeline event.
    """
    u = current_user()
    data = request.get_json() or {}
    txn_id        = data.get('transaction_id', '').strip()
    payment_method = data.get('payment_method', 'UPI').strip()

    if not txn_id:
        return jsonify({'error': 'transaction_id required'}), 400
    if payment_method not in PAYMENT_METHODS:
        return jsonify({'error': f'payment_method must be one of {PAYMENT_METHODS}'}), 400

    payment = db.get_payment_by_txn(txn_id)
    if not payment:
        return jsonify({'error': 'Transaction not found'}), 404
    if payment['user_id'] != u['id'] and u['role'] != 'Admin':
        return jsonify({'error': 'Forbidden'}), 403
    if payment['status'] == 'SUCCESS':
        return jsonify({'message': 'Already paid', 'payment': payment})

    # Update method then mark SUCCESS
    conn = db.get_conn()
    conn.execute("UPDATE payments SET payment_method=? WHERE transaction_id=?",
                 (payment_method, txn_id))
    conn.commit(); conn.close()

    confirmed = db.confirm_payment(txn_id)

    # Timeline event on the application
    app = db.get_application(confirmed['application_id'])
    if app:
        db.create_event(
            confirmed['application_id'],
            u['id'], u['name'], u.get('department', 'Applicant'),
            'submission',
            f'Processing fee paid.\n'
            f'Amount: ₹{confirmed["amount"]:,}\n'
            f'Method: {payment_method}\n'
            f'Transaction ID: {txn_id}',
            app['status']
        )
        db.create_notification(
            u['id'], confirmed['application_id'],
            'Payment Successful',
            f'₹{confirmed["amount"]:,} paid via {payment_method}. TXN: {txn_id}'
        )

    # Email confirmation
    email_service.notify_payment_success(
        to=u.get('email', ''),
        name=u['name'],
        app_id=confirmed['application_id'],
        project_name=confirmed.get('project_name', ''),
        amount=confirmed['amount'],
        transaction_id=txn_id,
        payment_method=payment_method,
        paid_at=confirmed['created_at']
    )

    db.log_audit(u['id'], 'PAYMENT_SUCCESS', confirmed['application_id'],
                 f'txn={txn_id} method={payment_method}')

    return jsonify({
        'message': 'Payment successful',
        'payment': confirmed
    })


# ── GET PAYMENT STATUS (for receipt page) ────────────────────────────────────
@payment_bp.route('/payment/<app_id>', methods=['GET'])
@login_required
def get_payment(app_id):
    """Return payment details for an application."""
    u = current_user()
    app = db.get_application(app_id)
    if not app:
        return jsonify({'error': 'Application not found'}), 404
    if app['created_by'] != u['id'] and u['role'] != 'Admin':
        return jsonify({'error': 'Forbidden'}), 403
    payment = db.get_payment_by_app(app_id)
    if not payment:
        return jsonify({'error': 'No payment record found for this application'}), 404
    return jsonify(payment)


# ── ADMIN: ALL PAYMENTS ───────────────────────────────────────────────────────
@payment_bp.route('/payment/all', methods=['GET'])
@login_required
@role_required('Admin')
def all_payments():
    return jsonify(db.get_all_payments())
