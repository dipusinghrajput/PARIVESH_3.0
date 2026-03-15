from flask import Blueprint, request, jsonify, session, send_file, current_app
from werkzeug.utils import secure_filename
from routes.auth import login_required, role_required, current_user
import db, ai_screening, email_service, os, uuid, json

app_bp = Blueprint('applications', __name__)
ALLOWED_EXT = {'pdf','docx','xlsx'}
MAX_FILE_SIZE = 20 * 1024 * 1024


def allowed_file(fn):
    return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_EXT

def save_file(file, application_id):
    if not allowed_file(file.filename):
        return None, 'Only PDF, DOCX, XLSX allowed'
    file.seek(0,2); size=file.tell(); file.seek(0)
    if size > MAX_FILE_SIZE:
        return None, 'File exceeds 20MB'
    ext = file.filename.rsplit('.',1)[1].lower()
    stored = f"{application_id}_{uuid.uuid4().hex[:8]}.{ext}"
    d = os.path.join(current_app.config['UPLOAD_FOLDER'], application_id)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, stored)
    file.save(path)
    return os.path.join(application_id, stored), None


# ── CHECKLIST / SECTORS ───────────────────────────────────────────────────────
@app_bp.route('/checklist/<sector>', methods=['GET'])
def get_checklist(sector):
    return jsonify(db.SECTOR_CHECKLISTS.get(sector, db.SECTOR_CHECKLISTS['Other']))

@app_bp.route('/sectors', methods=['GET'])
def get_sectors():
    return jsonify(list(db.SECTOR_CHECKLISTS.keys()))


# ── CREATE ────────────────────────────────────────────────────────────────────
@app_bp.route('/application/create', methods=['POST'])
@login_required
@role_required('PP','Admin')
def create_application():
    u = current_user()
    data = request.form
    for k in ['project_name','sector','category','location']:
        if not data.get(k):
            return jsonify({'error': f'Missing: {k}'}), 400
    app = db.create_application(
        project_name=data['project_name'], sector=data['sector'],
        category=data['category'], location=data['location'],
        description=data.get('description',''), created_by=u['id'],
        capacity=data.get('capacity',''), area_ha=data.get('area_ha','')
    )
    db.create_event(app['id'], u['id'], u['name'], u['department'] or 'Applicant',
                    'submission', 'Application created as Draft.', 'Draft')
    return jsonify({'message':'Created','application':app}), 201


# ── UPLOAD DOC ────────────────────────────────────────────────────────────────
@app_bp.route('/application/<app_id>/upload', methods=['POST'])
@login_required
@role_required('PP','Admin')
def upload_doc(app_id):
    u = current_user()
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    if app['created_by'] != u['id'] and u['role'] != 'Admin':
        return jsonify({'error':'Forbidden'}), 403
    if 'file' not in request.files:
        return jsonify({'error':'No file'}), 400
    file = request.files['file']
    doc_type     = request.form.get('doc_type','Document')
    is_affidavit = int(request.form.get('is_affidavit', 0))
    aff_type     = request.form.get('affidavit_type','')
    prev_id      = request.form.get('prev_id')
    path, err = save_file(file, app_id)
    if err: return jsonify({'error':err}), 400
    prev_doc = db.get_document(int(prev_id)) if prev_id else None
    version  = (prev_doc['version'] + 1) if prev_doc else 1
    doc = db.create_document(app_id, doc_type, file.filename, path, version, u['id'],
                              int(prev_id) if prev_id else None, is_affidavit, aff_type)
    return jsonify({'message':'Uploaded','document':doc}), 201


# ── SUBMIT → AI SCREEN ────────────────────────────────────────────────────────
@app_bp.route('/application/<app_id>/submit', methods=['POST'])
@login_required
@role_required('PP','Admin')
def submit_application(app_id):
    u = current_user()
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    if app['created_by'] != u['id'] and u['role'] != 'Admin':
        return jsonify({'error':'Forbidden'}), 403
    if app['status'] != 'Draft':
        return jsonify({'error':'Only Draft can be submitted'}), 400
    docs = db.get_documents_for_app(app_id)
    if not docs:
        return jsonify({'error':'Upload at least one document before submitting'}), 400

    db.update_application(app_id, status='AIScreening')
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Applicant',
                    'submission',
                    f'Application submitted with {len(docs)} document(s). AI pre-screening initiated.',
                    'AIScreening')

    passed, report, score = ai_screening.run_ai_screening(app_id)
    report_json = json.dumps(report)
    pp_email = app.get('creator_email','')
    pp_name  = app.get('creator_name','Applicant')

    if passed:
        db.update_application(app_id, status='Scrutiny', ai_score=score, ai_report=report_json)
        db.create_event(app_id, None, 'AI Screening Engine', 'AI System',
                        'ai_screen',
                        f'✅ AI Pre-Screen PASSED (Score: {score}/100)\n{len(report["checks_passed"])} checks passed. Forwarding to Scrutiny.',
                        'Scrutiny', ai_generated=1)
        db.notify_role('Scrutiny', app_id, 'New Application — AI Cleared',
                       f'{app_id} passed AI screening (score {score}). Ready for review.')
        db.create_notification(u['id'], app_id, 'Application Submitted',
                               f'Your application {app_id} passed AI pre-screening → Scrutiny queue.')
        # Email PP
        email_service.notify_ai_passed(pp_email, pp_name, app_id, score)
    else:
        db.update_application(app_id, status='EDS', ai_score=score, ai_report=report_json)
        eds_pts = '\n'.join(f'• {p}' for p in report['suggested_eds_points'])
        db.create_event(app_id, None, 'AI Screening Engine', 'AI System',
                        'ai_screen',
                        f'❌ AI Pre-Screen FAILED (Score: {score}/100)\n\nIssues found:\n{eds_pts}',
                        'EDS', ai_generated=1)
        db.create_notification(u['id'], app_id, 'AI Pre-Screen Failed — Action Required',
                               f'Your application {app_id} failed AI pre-screening. Fix issues and resubmit.')
        # Email PP with issues
        email_service.notify_ai_failed(pp_email, pp_name, app_id,
                                        score, report.get('issues', []))

    db.log_audit(u['id'], 'SUBMIT', app_id, f'AI score={score}')
    return jsonify({'message':'Submitted','application':db.get_application(app_id),'ai_report':report})


# ── LIST / GET ─────────────────────────────────────────────────────────────────
@app_bp.route('/application/list', methods=['GET'])
@login_required
def list_applications():
    u = current_user()
    return jsonify(db.list_applications(
        user_id=u['id'], role=u['role'],
        status=request.args.get('status'),
        sector=request.args.get('sector'),
        search=request.args.get('search','').strip() or None
    ))

@app_bp.route('/application/<app_id>', methods=['GET'])
@login_required
def get_application(app_id):
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    return jsonify(app)


# ── LIST AVAILABLE OFFICERS BY ROLE ──────────────────────────────────────────
@app_bp.route('/officers/<role>', methods=['GET'])
@login_required
@role_required('Admin','Scrutiny','MoM')
def list_officers(role):
    """Return all users of a given role with full contact details."""
    allowed = ['Scrutiny','MoM','Admin']
    if role not in allowed:
        return jsonify({'error': f'Role must be one of {allowed}'}), 400
    officers = db.get_users_by_role(role)
    # strip password_hash
    return jsonify([{k:v for k,v in o.items() if k != 'password_hash'} for o in officers])


# ── SCRUTINY: ASSIGN (Admin assigns a specific Scrutiny officer) ──────────────
@app_bp.route('/scrutiny/assign/<app_id>', methods=['POST'])
@login_required
@role_required('Admin','Scrutiny')
def assign_scrutiny(app_id):
    u = current_user()
    app = db.get_application(app_id)
    if not app: return jsonify({'error': 'Not found'}), 404
    if app['status'] not in ('Scrutiny', 'Resubmitted'):
        return jsonify({'error': f'Cannot assign: application is in {app["status"]} status'}), 400

    data = request.get_json() or {}
    officer_id = data.get('officer_id')
    if not officer_id:
        return jsonify({'error': 'officer_id is required'}), 400

    officer = db.get_user_by_id(int(officer_id))
    if not officer or officer['role'] not in ('Scrutiny', 'Admin'):
        return jsonify({'error': 'Selected user is not a Scrutiny officer'}), 400

    prev_officer = app.get('officer_name')
    db.update_application(app_id, assigned_officer=officer['id'])

    msg = f'Scrutiny Officer assigned: {officer["name"]} ({officer["department"] or "Scrutiny Division"})'
    if prev_officer:
        msg = f'Scrutiny Officer reassigned from {prev_officer} to {officer["name"]}.'
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Admin',
                    'verification', msg, app['status'])
    db.create_notification(app['created_by'], app_id, 'Scrutiny Officer Assigned',
                           f'Your application {app_id} has been assigned to {officer["name"]} ({officer["department"] or "Scrutiny"}).')
    email_service.notify_scrutiny_assigned(
        app.get('creator_email', ''), app.get('creator_name', 'Applicant'),
        app_id, officer['name'], officer.get('department', ''), officer.get('email', ''), officer.get('phone', '')
    )
    db.log_audit(u['id'], 'ASSIGN_SCRUTINY', app_id, f'officer={officer["name"]}')
    return jsonify({'message': f'Assigned to {officer["name"]}', 'application': db.get_application(app_id)})


# ── SCRUTINY: UNASSIGN ────────────────────────────────────────────────────────
@app_bp.route('/scrutiny/unassign/<app_id>', methods=['POST'])
@login_required
@role_required('Admin','Scrutiny')
def unassign_scrutiny(app_id):
    u = current_user()
    app = db.get_application(app_id)
    if not app: return jsonify({'error': 'Not found'}), 404
    if not app.get('assigned_officer'):
        return jsonify({'error': 'No Scrutiny officer currently assigned'}), 400

    prev = app.get('officer_name', 'Officer')
    data = request.get_json() or {}
    reason = data.get('reason', 'Unassigned by administrator.')

    db.update_application(app_id, assigned_officer=None)
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Admin',
                    'verification',
                    f'Scrutiny Officer {prev} unassigned from application.\nReason: {reason}',
                    app['status'])
    db.create_notification(app['created_by'], app_id, 'Scrutiny Officer Unassigned',
                           f'The Scrutiny officer for {app_id} has been unassigned. A new officer will be assigned.')
    email_service.notify_scrutiny_unassigned(
        app.get('creator_email', ''), app.get('creator_name', 'Applicant'), app_id, prev
    )
    db.log_audit(u['id'], 'UNASSIGN_SCRUTINY', app_id, reason)
    return jsonify({'message': f'{prev} unassigned', 'application': db.get_application(app_id)})


# ── SCRUTINY: RAISE EDS ────────────────────────────────────────────────────────
@app_bp.route('/scrutiny/raise-eds', methods=['POST'])
@login_required
@role_required('Scrutiny','Admin')
def raise_eds():
    u = current_user()
    data = request.get_json() or {}
    app_id = data.get('application_id')
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    if app['status'] not in ('Scrutiny','Resubmitted'):
        return jsonify({'error':'Invalid status'}), 400
    issue   = data.get('issue_description','')
    req_doc = data.get('requested_document','')
    msg = f'EDS Raised.\nIssue: {issue}'
    if req_doc: msg += f'\nRequested Document: {req_doc}'
    db.update_application(app_id, status='EDS')
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Scrutiny',
                    'issue', msg, 'EDS')
    db.create_notification(app['created_by'], app_id, 'EDS Raised — Action Required',
                           f'EDS raised on {app_id}. Please respond with required documents.')
    # Email PP
    email_service.notify_eds_raised(
        app.get('creator_email',''), app.get('creator_name','Applicant'),
        app_id, issue, req_doc
    )
    db.log_audit(u['id'],'RAISE_EDS', app_id, issue)
    return jsonify({'message':'EDS raised','application':db.get_application(app_id)})


@app_bp.route('/scrutiny/refer/<app_id>', methods=['POST'])
@login_required
@role_required('Scrutiny','Admin')
def refer_to_meeting(app_id):
    u = current_user()
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    if app['status'] not in ('Scrutiny','Resubmitted'):
        return jsonify({'error':'Invalid status'}), 400
    data = request.get_json() or {}
    db.update_application(app_id, status='Referred')
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Scrutiny',
                    'meeting',
                    f'Application referred to Expert Appraisal Committee. {data.get("remarks","")}',
                    'Referred')
    db.notify_role('MoM', app_id, 'Application Referred', f'{app_id} referred for EAC meeting.')
    db.create_notification(app['created_by'], app_id, 'Application Referred to EAC',
                           f'Your application {app_id} has been referred to the Expert Appraisal Committee.')
    # Email PP
    email_service.notify_referred(
        app.get('creator_email',''), app.get('creator_name','Applicant'), app_id
    )
    return jsonify({'message':'Referred','application':db.get_application(app_id)})


@app_bp.route('/scrutiny/verify/<app_id>', methods=['POST'])
@login_required
@role_required('Scrutiny','Admin')
def verify_docs(app_id):
    u = current_user()
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    data = request.get_json() or {}
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Scrutiny',
                    'verification',
                    f'Documents verified by {u["name"]}. {data.get("remarks","")}',
                    app['status'])
    db.create_notification(app['created_by'], app_id, 'Documents Verified',
                           f'Documents for {app_id} verified by the Scrutiny Officer.')
    return jsonify({'message':'Verified'})


# ── EDS RESPONSE ──────────────────────────────────────────────────────────────
@app_bp.route('/application/respond', methods=['POST'])
@login_required
@role_required('PP','Admin')
def respond_to_eds():
    u = current_user()
    app_id = request.form.get('application_id')
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    if app['created_by'] != u['id'] and u['role'] != 'Admin':
        return jsonify({'error':'Forbidden'}), 403
    if app['status'] != 'EDS':
        return jsonify({'error':'Must be in EDS status'}), 400

    response_text = request.form.get('response_text','')
    updated_docs  = []
    for key in request.files:
        file     = request.files[key]
        doc_type = request.form.get(f'{key}_type', key)
        prev_id  = request.form.get(f'{key}_prev_id')
        is_aff   = int(request.form.get(f'{key}_is_affidavit', 0))
        aff_type = request.form.get(f'{key}_affidavit_type','')
        path, err = save_file(file, app_id)
        if err: return jsonify({'error':err}), 400
        prev_doc = db.get_document(int(prev_id)) if prev_id else None
        version  = (prev_doc['version']+1) if prev_doc else 1
        doc = db.create_document(app_id, doc_type, file.filename, path, version, u['id'],
                                  int(prev_id) if prev_id else None, is_aff, aff_type)
        updated_docs.append(doc)

    db.update_application(app_id, status='Resubmitted')
    msg = 'EDS response submitted.'
    if response_text: msg += f'\n{response_text}'
    first = updated_docs[0] if updated_docs else None
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Applicant',
                    'response', msg, 'Resubmitted', first['id'] if first else None)
    for doc in updated_docs[1:]:
        db.create_event(app_id, u['id'], u['name'], u['department'] or 'Applicant',
                        'file_update', f'Document updated: {doc["document_type"]} (v{doc["version"]})',
                        'Resubmitted', doc['id'])
    db.notify_role('Scrutiny', app_id, 'EDS Response Submitted', f'{app_id} resubmitted by applicant.')
    return jsonify({'message':'Response submitted','application':db.get_application(app_id)})


# ── MOM: ASSIGN (Admin assigns a specific MoM officer) ───────────────────────
@app_bp.route('/mom/assign/<app_id>', methods=['POST'])
@login_required
@role_required('Admin','MoM')
def assign_mom(app_id):
    u = current_user()
    app = db.get_application(app_id)
    if not app: return jsonify({'error': 'Not found'}), 404
    if app['status'] not in ('Referred', 'MoMGenerated'):
        return jsonify({'error': f'Cannot assign: application is in {app["status"]} status'}), 400
    data = request.get_json() or {}
    officer_id = data.get('officer_id')
    if not officer_id:
        return jsonify({'error': 'officer_id is required'}), 400
    officer = db.get_user_by_id(int(officer_id))
    if not officer or officer['role'] not in ('MoM', 'Admin'):
        return jsonify({'error': 'Selected user is not a MoM Secretariat officer'}), 400
    prev = app.get('mom_officer_name')
    db.update_application(app_id, mom_officer_id=officer['id'])
    msg = f'MoM Secretariat officer assigned: {officer["name"]} ({officer["department"] or "MoM Secretariat"})'
    if prev:
        msg = f'MoM officer reassigned from {prev} to {officer["name"]}.'
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Admin',
                    'meeting', msg, app['status'])
    db.create_notification(app['created_by'], app_id, 'MoM Officer Assigned',
                           f'MoM Secretariat officer {officer["name"]} has been assigned to {app_id}.')
    email_service.notify_mom_assigned(
        app.get('creator_email', ''), app.get('creator_name', 'Applicant'),
        app_id, officer['name'], officer.get('department', ''),
        officer.get('email', ''), officer.get('phone', '')
    )
    db.log_audit(u['id'], 'ASSIGN_MOM', app_id, f'officer={officer["name"]}')
    return jsonify({'message': f'MoM officer assigned: {officer["name"]}', 'application': db.get_application(app_id)})


# ── MOM: UNASSIGN ─────────────────────────────────────────────────────────────
@app_bp.route('/mom/unassign/<app_id>', methods=['POST'])
@login_required
@role_required('Admin','MoM')
def unassign_mom(app_id):
    u = current_user()
    app = db.get_application(app_id)
    if not app: return jsonify({'error': 'Not found'}), 404
    if not app.get('mom_officer_id'):
        return jsonify({'error': 'No MoM officer currently assigned'}), 400
    prev = app.get('mom_officer_name', 'MoM Officer')
    data = request.get_json() or {}
    reason = data.get('reason', 'Unassigned by administrator.')
    db.update_application(app_id, mom_officer_id=None)
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Admin',
                    'meeting',
                    f'MoM Secretariat officer {prev} unassigned.\nReason: {reason}',
                    app['status'])
    db.create_notification(app['created_by'], app_id, 'MoM Officer Unassigned',
                           f'The MoM officer for {app_id} has been unassigned. A new officer will be assigned.')
    email_service.notify_mom_unassigned(
        app.get('creator_email', ''), app.get('creator_name', 'Applicant'), app_id, prev
    )
    db.log_audit(u['id'], 'UNASSIGN_MOM', app_id, reason)
    return jsonify({'message': f'{prev} unassigned', 'application': db.get_application(app_id)})


# ── MOM: GENERATE ─────────────────────────────────────────────────────────────
@app_bp.route('/mom/generate', methods=['POST'])
@login_required
@role_required('MoM','Admin')
def generate_mom():
    u = current_user()
    app_id = request.form.get('application_id')
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    if app['status'] != 'Referred':
        return jsonify({'error':'Must be Referred'}), 400
    discussion = request.form.get('discussion','')
    doc = None
    if 'mom_document' in request.files:
        file = request.files['mom_document']
        path, err = save_file(file, app_id)
        if err: return jsonify({'error':err}), 400
        doc = db.create_document(app_id,'MoM Document', file.filename, path, 1, u['id'])
    # Auto-assign this MoM officer if none assigned
    updates = {'status':'MoMGenerated'}
    if not app.get('mom_officer_id'):
        updates['mom_officer_id'] = u['id']
    db.update_application(app_id, **updates)
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'MoM Secretariat',
                    'meeting', f'Minutes of Meeting generated.\nDiscussion: {discussion}',
                    'MoMGenerated', doc['id'] if doc else None)
    db.create_notification(app['created_by'], app_id, 'MoM Generated',
                           f'Minutes of Meeting have been generated for {app_id}.')
    email_service.notify_mom_generated(
        app.get('creator_email',''), app.get('creator_name','Applicant'), app_id
    )
    return jsonify({'message':'MoM generated','application':db.get_application(app_id)})


# ── FINALIZE ──────────────────────────────────────────────────────────────────
@app_bp.route('/application/<app_id>/finalize', methods=['POST'])
@login_required
@role_required('Admin','MoM')
def finalize(app_id):
    u = current_user()
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    if app['status'] != 'MoMGenerated':
        return jsonify({'error':'Must be MoMGenerated'}), 400
    data = request.get_json() or {}
    decision = data.get('decision','GRANTED')
    remarks  = data.get('remarks','')
    db.update_application(app_id, status='Finalized')
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Ministry',
                    'decision',
                    f'Environmental Clearance {decision}. {remarks}',
                    'Finalized')
    db.create_notification(app['created_by'], app_id, f'Final Decision: EC {decision}',
                           f'Final decision on {app_id}: {decision}.')
    email_service.notify_final_decision(
        app.get('creator_email',''), app.get('creator_name','Applicant'),
        app_id, decision, remarks
    )
    return jsonify({'message':'Finalized','application':db.get_application(app_id)})


# ── MEETINGS ──────────────────────────────────────────────────────────────────
@app_bp.route('/meetings', methods=['GET'])
@login_required
def all_meetings():
    return jsonify(db.get_all_meetings())

@app_bp.route('/meetings/app/<app_id>', methods=['GET'])
@login_required
def app_meetings(app_id):
    return jsonify(db.get_meetings_for_app(app_id))

@app_bp.route('/meetings/create', methods=['POST'])
@login_required
@role_required('MoM','Admin')
def create_meeting():
    u = current_user()
    data = request.get_json() or {}
    app_id = data.get('application_id')
    app = db.get_application(app_id) if app_id else None
    gist = ai_screening.generate_gist(app_id) if app_id else ''
    meeting = db.create_meeting(
        application_id=app_id,
        title=data.get('title','EAC Meeting'),
        scheduled_date=data.get('scheduled_date',''),
        agenda=data.get('agenda',''),
        created_by=u['id'],
        gist_text=gist
    )
    if app:
        db.create_event(app_id, u['id'], u['name'], u['department'] or 'MoM Secretariat',
                        'meeting',
                        f'Meeting scheduled: {meeting["title"]} on {meeting["scheduled_date"]}.',
                        app['status'])
        db.create_notification(app['created_by'], app_id, 'EAC Meeting Scheduled',
                               f'A meeting has been scheduled for {app_id} on {meeting["scheduled_date"]}.')
        email_service.notify_meeting_scheduled(
            app.get('creator_email',''), app.get('creator_name','Applicant'),
            app_id, meeting['title'], meeting['scheduled_date']
        )
    return jsonify({'message':'Meeting created','meeting':meeting}), 201

@app_bp.route('/meetings/<int:mid>', methods=['GET'])
@login_required
def get_meeting(mid):
    m = db.get_meeting(mid)
    if not m: return jsonify({'error':'Not found'}), 404
    return jsonify(m)

@app_bp.route('/meetings/<int:mid>/update', methods=['POST'])
@login_required
@role_required('MoM','Admin')
def update_meeting(mid):
    data = request.get_json() or {}
    allowed = ['notes','agenda','status','scheduled_date']
    updates = {k: v for k,v in data.items() if k in allowed}
    db.update_meeting(mid, **updates)
    return jsonify({'message':'Updated','meeting':db.get_meeting(mid)})

@app_bp.route('/meetings/<int:mid>/gist', methods=['GET'])
@login_required
def get_gist(mid):
    m = db.get_meeting(mid)
    if not m: return jsonify({'error':'Not found'}), 404
    if m.get('application_id') and not m.get('gist_text'):
        gist = ai_screening.generate_gist(m['application_id'])
        db.update_meeting(mid, gist_text=gist)
        m['gist_text'] = gist
    return jsonify({'gist': m.get('gist_text','')})

@app_bp.route('/application/<app_id>/gist', methods=['GET'])
@login_required
def app_gist(app_id):
    return jsonify({'gist': ai_screening.generate_gist(app_id)})


# ── TIMELINE / DOCS ───────────────────────────────────────────────────────────
@app_bp.route('/timeline/<app_id>', methods=['GET'])
@login_required
def get_timeline(app_id):
    return jsonify(db.get_timeline(app_id, request.args.get('type')))

@app_bp.route('/documents/<app_id>', methods=['GET'])
@login_required
def get_documents(app_id):
    return jsonify(db.get_documents_for_app(app_id))

@app_bp.route('/download/<int:doc_id>', methods=['GET'])
@login_required
def download_document(doc_id):
    doc = db.get_document(doc_id)
    if not doc: return jsonify({'error':'Not found'}), 404
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], doc['file_path'])
    if not os.path.exists(path): return jsonify({'error':'File missing'}), 404
    return send_file(path, as_attachment=True, download_name=doc['original_name'])

@app_bp.route('/ai-report/<app_id>', methods=['GET'])
@login_required
def get_ai_report(app_id):
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    report = json.loads(app['ai_report']) if app.get('ai_report') else {}
    return jsonify({'score': app.get('ai_score',0), 'report': report})


# ── NOTIFICATIONS ─────────────────────────────────────────────────────────────
@app_bp.route('/notifications', methods=['GET'])
@login_required
def get_notifications():
    return jsonify(db.get_notifications(current_user()['id']))

@app_bp.route('/notifications/read', methods=['POST'])
@login_required
def mark_read():
    db.mark_all_read(current_user()['id'])
    return jsonify({'message':'Done'})


# ── SEARCH ────────────────────────────────────────────────────────────────────
@app_bp.route('/search', methods=['GET'])
@login_required
def search():
    q = request.args.get('q','').strip()
    if not q: return jsonify([])
    return jsonify(db.list_applications(search=q))


# ── CHATBOT ───────────────────────────────────────────────────────────────────
# ── CHATBOT ───────────────────────────────────────────────────────────────────
from chatbot import PariveshChatbot as _Bot
_bot = _Bot()   # single instance, reused across requests

@app_bp.route('/chatbot', methods=['POST'])
@login_required
def chatbot():
    u    = current_user()
    data = request.get_json() or {}
    msg  = data.get('message', '').strip()
    # Accept optional app_id from the frontend (when user is on a case file page)
    app_id_hint = data.get('app_id') or None
    reply = _bot.reply(msg, user_id=u['id'], app_id_hint=app_id_hint)
    return jsonify({'reply': reply})
