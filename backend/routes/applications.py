from flask import Blueprint, request, jsonify, session, send_file, current_app
from werkzeug.utils import secure_filename
from routes.auth import login_required, role_required, current_user
import db, ai_screening, os, uuid, json

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


# ── SECTOR CHECKLIST ─────────────────────────────────────────────────────────
@app_bp.route('/checklist/<sector>', methods=['GET'])
def get_checklist(sector):
    cl = db.SECTOR_CHECKLISTS.get(sector, db.SECTOR_CHECKLISTS['Other'])
    return jsonify(cl)

@app_bp.route('/sectors', methods=['GET'])
def get_sectors():
    return jsonify(list(db.SECTOR_CHECKLISTS.keys()))


# ── CREATE APPLICATION ────────────────────────────────────────────────────────
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


# ── UPLOAD DOCUMENT (to draft) ────────────────────────────────────────────────
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
    doc_type    = request.form.get('doc_type', 'Document')
    is_affidavit= int(request.form.get('is_affidavit', 0))
    aff_type    = request.form.get('affidavit_type', '')
    prev_id     = request.form.get('prev_id')

    path, err = save_file(file, app_id)
    if err: return jsonify({'error': err}), 400

    prev_doc = db.get_document(int(prev_id)) if prev_id else None
    version  = (prev_doc['version'] + 1) if prev_doc else 1
    doc = db.create_document(app_id, doc_type, file.filename, path, version, u['id'],
                              int(prev_id) if prev_id else None, is_affidavit, aff_type)
    return jsonify({'message':'Uploaded','document':doc}), 201


# ── SUBMIT (triggers AI screening) ───────────────────────────────────────────
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
                    'submission', f'Application submitted with {len(docs)} document(s). AI pre-screening initiated.',
                    'AIScreening')

    # Run AI screening
    passed, report, score = ai_screening.run_ai_screening(app_id)
    report_json = json.dumps(report)

    if passed:
        db.update_application(app_id, status='Scrutiny', ai_score=score, ai_report=report_json)
        db.create_event(app_id, None, 'AI Screening Engine', 'AI System',
                        'ai_screen',
                        f'✅ AI Pre-Screen PASSED (Score: {score}/100)\n{len(report["checks_passed"])} checks passed. Forwarding to Scrutiny.',
                        'Scrutiny', ai_generated=1)
        db.notify_role('Scrutiny', app_id, 'New Application — AI Cleared',
                       f'{app_id} passed AI screening (score {score}). Ready for review.')
        db.create_notification(u['id'], app_id, 'Application Submitted',
                               f'Your application {app_id} passed AI pre-screening and is now in the Scrutiny queue.')
    else:
        db.update_application(app_id, status='EDS', ai_score=score, ai_report=report_json)
        eds_points = '\n'.join(f'• {p}' for p in report['suggested_eds_points'])
        db.create_event(app_id, None, 'AI Screening Engine', 'AI System',
                        'ai_screen',
                        f'❌ AI Pre-Screen FAILED (Score: {score}/100)\n\nIssues found:\n{eds_points}',
                        'EDS', ai_generated=1)
        db.create_notification(u['id'], app_id, 'AI Pre-Screen Failed — Action Required',
                               f'Your application {app_id} failed AI pre-screening. Please address the issues and resubmit.')

    db.log_audit(u['id'], 'SUBMIT', app_id, f'AI score={score}')
    return jsonify({'message':'Submitted','application':db.get_application(app_id),
                    'ai_report':report})


# ── LIST ──────────────────────────────────────────────────────────────────────
@app_bp.route('/application/list', methods=['GET'])
@login_required
def list_applications():
    u = current_user()
    apps = db.list_applications(
        user_id=u['id'], role=u['role'],
        status=request.args.get('status'),
        sector=request.args.get('sector'),
        search=request.args.get('search','').strip() or None
    )
    return jsonify(apps)

@app_bp.route('/application/<app_id>', methods=['GET'])
@login_required
def get_application(app_id):
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    return jsonify(app)


# ── SCRUTINY ACTIONS ──────────────────────────────────────────────────────────
@app_bp.route('/scrutiny/begin/<app_id>', methods=['POST'])
@login_required
@role_required('Scrutiny','Admin')
def begin_scrutiny(app_id):
    u = current_user()
    app = db.get_application(app_id)
    if not app: return jsonify({'error':'Not found'}), 404
    if app['status'] not in ('Scrutiny','Resubmitted'):
        return jsonify({'error': f'Invalid status: {app["status"]}'}), 400
    db.update_application(app_id, assigned_officer=u['id'])
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Scrutiny',
                    'verification', f'Application assigned to {u["name"]} for scrutiny review.', app['status'])
    db.create_notification(app['created_by'], app_id, 'Scrutiny Assigned',
                           f'Your application {app_id} has been assigned to {u["name"]}.')
    return jsonify({'message':'Assigned','application':db.get_application(app_id)})

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
    issue = data.get('issue_description','')
    req   = data.get('requested_document','')
    msg   = f'EDS Raised.\nIssue: {issue}'
    if req: msg += f'\nRequested Document: {req}'
    db.update_application(app_id, status='EDS')
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Scrutiny',
                    'issue', msg, 'EDS')
    db.create_notification(app['created_by'], app_id, 'EDS Raised — Action Required',
                           f'EDS raised on {app_id}. Please respond.')
    db.log_audit(u['id'],'RAISE_EDS',app_id,issue)
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
    db.create_notification(app['created_by'], app_id, 'Application Referred',
                           f'Your application {app_id} is referred to the EAC.')
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
                           f'Documents for {app_id} have been verified by the Scrutiny Officer.')
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
        prev_doc  = db.get_document(int(prev_id)) if prev_id else None
        version   = (prev_doc['version']+1) if prev_doc else 1
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
    db.notify_role('Scrutiny', app_id, 'EDS Response Submitted', f'{app_id} resubmitted.')
    return jsonify({'message':'Response submitted','application':db.get_application(app_id)})


# ── MOM ───────────────────────────────────────────────────────────────────────
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
        doc = db.create_document(app_id, 'MoM Document', file.filename, path, 1, u['id'])
    db.update_application(app_id, status='MoMGenerated')
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'MoM Secretariat',
                    'meeting', f'Minutes of Meeting generated.\nDiscussion: {discussion}',
                    'MoMGenerated', doc['id'] if doc else None)
    db.create_notification(app['created_by'], app_id, 'MoM Generated', f'MoM generated for {app_id}.')
    return jsonify({'message':'MoM generated','application':db.get_application(app_id)})

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
    db.update_application(app_id, status='Finalized')
    db.create_event(app_id, u['id'], u['name'], u['department'] or 'Ministry',
                    'decision',
                    f'Environmental Clearance {data.get("decision","GRANTED")}. {data.get("remarks","")}',
                    'Finalized')
    db.create_notification(app['created_by'], app_id, 'Final Decision Issued',
                           f'Final decision on {app_id}: {data.get("decision","GRANTED")}.')
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
                        'meeting', f'Meeting scheduled: {meeting["title"]} on {meeting["scheduled_date"]}.',
                        app['status'])
        db.create_notification(app['created_by'], app_id, 'Meeting Scheduled',
                               f'A meeting has been scheduled for {app_id} on {meeting["scheduled_date"]}.')
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


# ── TIMELINE ─────────────────────────────────────────────────────────────────
@app_bp.route('/timeline/<app_id>', methods=['GET'])
@login_required
def get_timeline(app_id):
    return jsonify(db.get_timeline(app_id, request.args.get('type')))

# ── DOCUMENTS ─────────────────────────────────────────────────────────────────
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

# ── AI REPORT ─────────────────────────────────────────────────────────────────
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
CHATBOT_KB = {
    'document': 'Required documents vary by sector. Go to New Application → select your sector to see the checklist. Common docs: EMP, Pre-feasibility Report, Processing Fee, Affidavit, Forest NOC.',
    'affidavit': 'Affidavits confirm compliance with environmental rules, mining safety, Supreme Court guidelines. Upload a signed affidavit during application submission.',
    'eds': 'EDS (Environmental Data Shortfall) is raised when documents are incomplete. You will get a notification, then must upload the missing/corrected documents and resubmit.',
    'status': 'Track your application status on the Dashboard. Click any application to open the full Case File with timeline.',
    'submit': 'To submit: 1) Create application 2) Upload all required sector-specific documents 3) Upload affidavit 4) Click Submit. AI will pre-screen your application.',
    'ai': 'AI Pre-Screening automatically checks for missing documents, invalid file types, incomplete project details, and missing EMP/fee documents.',
    'meeting': 'Applications are referred to the Expert Appraisal Committee (EAC) for a meeting after Scrutiny. Minutes of Meeting (MoM) are generated after the meeting.',
    'category': 'Category A projects are appraised at the Central level. Category B1 and B2 are state-level. Category is based on project type and scale.',
    'sector': 'Supported sectors: Sand Mining, Limestone Mining, Brick Kiln, Infrastructure, Industry, Energy, Coastal, Other. Each has a predefined document checklist.',
    'download': 'All uploaded documents are securely stored. Login and go to the Case File page to download any document.',
    'contact': 'For assistance, contact the Scrutiny Division at scrutiny@parivesh.gov.in or call the helpdesk.',
    'timeline': 'The Case File page shows a complete timeline of every action: submissions, EDS, document uploads, meetings, and decisions — with timestamps and actor names.',
}

@app_bp.route('/chatbot', methods=['POST'])
@login_required
def chatbot():
    data = request.get_json() or {}
    msg  = data.get('message','').lower().strip()
    if not msg:
        return jsonify({'reply':'Please type your question.'})
    for keyword, reply in CHATBOT_KB.items():
        if keyword in msg:
            return jsonify({'reply': reply})
    # Fallback
    return jsonify({'reply': (
        'I can help with: document requirements, affidavit upload, EDS process, '
        'application submission, AI screening, meeting process, sector checklists, '
        'and application tracking. Please ask about any of these topics!'
    )})
