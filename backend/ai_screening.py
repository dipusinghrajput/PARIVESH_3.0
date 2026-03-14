"""
ai_screening.py — Rule-based AI pre-screening engine for PARIVESH 3.0
No external AI API required. Uses deterministic document/data checks.
"""
import db


def run_ai_screening(app_id):
    """
    Runs rule-based AI pre-screening on a submitted application.
    Returns (passed: bool, report: dict, score: int)
    """
    app = db.get_application(app_id)
    if not app:
        return False, {'error': 'Application not found'}, 0

    docs = db.get_documents_for_app(app_id)
    sector = app.get('sector', 'Other')
    checklist = db.SECTOR_CHECKLISTS.get(sector, db.SECTOR_CHECKLISTS['Other'])
    mandatory = checklist['mandatory']

    uploaded_types = {d['document_type'].strip() for d in docs}
    uploaded_names = {d['original_name'].lower() for d in docs}
    has_affidavit  = any(d.get('is_affidavit') for d in docs)

    issues        = []
    warnings      = []
    eds_points    = []
    checks_passed = []

    # ── CHECK 1: Mandatory document presence ─────────────────────────────────
    missing_mandatory = []
    for doc_type in mandatory:
        if doc_type not in uploaded_types and 'Affidavit' not in doc_type:
            missing_mandatory.append(doc_type)

    if missing_mandatory:
        issues.append({
            'category': 'Missing Mandatory Documents',
            'items': missing_mandatory
        })
        eds_points.extend([f"Upload required document: {d}" for d in missing_mandatory])
    else:
        checks_passed.append('All mandatory documents uploaded')

    # ── CHECK 2: Affidavit presence ──────────────────────────────────────────
    affidavit_docs = [d for d in docs if d.get('is_affidavit')]
    if not affidavit_docs:
        issues.append({'category': 'Missing Affidavit', 'items': ['No compliance affidavit uploaded']})
        eds_points.append('Upload signed compliance affidavit')
    else:
        checks_passed.append(f'{len(affidavit_docs)} affidavit(s) uploaded')

    # ── CHECK 3: File type validation ────────────────────────────────────────
    bad_files = [d['original_name'] for d in docs
                 if not d['original_name'].lower().endswith(('.pdf', '.docx', '.xlsx'))]
    if bad_files:
        issues.append({'category': 'Invalid File Types', 'items': bad_files})
    else:
        checks_passed.append('All file types are valid (PDF/DOCX/XLSX)')

    # ── CHECK 4: Project detail completeness ─────────────────────────────────
    incomplete_fields = []
    if not app.get('description') or len(app.get('description','')) < 20:
        incomplete_fields.append('Project description is too brief (minimum 20 characters)')
    if not app.get('capacity'):
        incomplete_fields.append('Project capacity / production volume not specified')
    if not app.get('area_ha'):
        incomplete_fields.append('Project area (in hectares) not specified')
    if incomplete_fields:
        warnings.extend(incomplete_fields)
        eds_points.extend(incomplete_fields)
    else:
        checks_passed.append('Project details are complete')

    # ── CHECK 5: KML / Map file ───────────────────────────────────────────────
    has_map = any('kml' in n or 'map' in n or 'survey' in n or 'location' in n
                  for n in uploaded_names)
    if not has_map and sector in ('Sand Mining', 'Limestone Mining', 'Infrastructure'):
        warnings.append('KML/Map file not detected — recommended for spatial verification')

    # ── CHECK 6: EMP presence ────────────────────────────────────────────────
    has_emp = 'Environmental Management Plan (EMP)' in uploaded_types or \
              any('emp' in n or 'environmental management' in n for n in uploaded_names)
    if not has_emp:
        issues.append({'category': 'Missing Environmental Report', 'items': ['EMP not found']})
        eds_points.append('Upload Environmental Management Plan (EMP)')
    else:
        checks_passed.append('Environmental Management Plan found')

    # ── CHECK 7: Processing fee ───────────────────────────────────────────────
    has_fee = 'Processing Fee Details' in uploaded_types or \
              any('fee' in n or 'challan' in n or 'payment' in n for n in uploaded_names)
    if not has_fee:
        issues.append({'category': 'Missing Fee Document', 'items': ['Processing fee document not found']})
        eds_points.append('Upload processing fee receipt / challan')
    else:
        checks_passed.append('Processing fee document found')

    # ── SCORING ───────────────────────────────────────────────────────────────
    total_checks = 7
    failed_checks = len(issues)
    passed_checks = total_checks - failed_checks
    score = int((passed_checks / total_checks) * 100)

    passed = len(issues) == 0  # Must have zero hard issues to auto-pass

    report = {
        'score': score,
        'passed': passed,
        'sector': sector,
        'total_docs_uploaded': len(docs),
        'mandatory_required': len(mandatory),
        'issues': issues,
        'warnings': warnings,
        'checks_passed': checks_passed,
        'suggested_eds_points': eds_points,
        'recommendation': 'PASS — Forward to Scrutiny Queue' if passed else
                          'FAIL — Return EDS to Applicant'
    }

    return passed, report, score


def generate_gist(app_id):
    """Auto-generate a Gist document text from application data."""
    app = db.get_application(app_id)
    if not app: return ''
    docs  = db.get_documents_for_app(app_id)
    evts  = db.get_timeline(app_id)
    meets = db.get_meetings_for_app(app_id)

    doc_list = '\n'.join(f"  • {d['document_type']} (v{d['version']}) — {d['original_name']}"
                         for d in docs) or '  • No documents uploaded'

    issues = [e for e in evts if e['event_type'] == 'issue']
    issue_list = '\n'.join(f"  • [{e['datetime'][:10]}] {e['message'][:120]}"
                            for e in issues) or '  • No EDS issues raised'

    gist = f"""
PARIVESH 3.0 — APPLICATION GIST DOCUMENT
==========================================
Generated: {datetime.now_str()}

PROJECT DETAILS
---------------
Application ID  : {app['id']}
Project Name    : {app['project_name']}
Sector          : {app['sector']}
Category        : {app['category']}
Location        : {app['location']}
Capacity        : {app.get('capacity') or 'Not specified'}
Area (Ha)       : {app.get('area_ha') or 'Not specified'}
Applicant       : {app.get('creator_name', '–')}
Current Status  : {app['status']}
Submitted On    : {app['created_at'][:10]}

PROJECT DESCRIPTION
-------------------
{app.get('description') or 'Not provided'}

DOCUMENT COMPLIANCE STATUS
--------------------------
Total Documents Uploaded: {len(docs)}
{doc_list}

EDS / ISSUES RAISED
-------------------
{issue_list}

MEETING HISTORY
---------------
{chr(10).join(f"  • {m['title']} — {m['scheduled_date']} [{m['status']}]" for m in meets) or '  • No meetings scheduled'}

ENVIRONMENTAL CLEARANCE SUMMARY
---------------------------------
This application is for Environmental Clearance under the EIA Notification 2006
(as amended). The project falls under Category {app['category']} of the Schedule
to the said notification.

The Expert Appraisal Committee is requested to examine this case and make
appropriate recommendations for grant / rejection of Environmental Clearance.

[END OF GIST DOCUMENT]
""".strip()
    return gist


class datetime:
    @staticmethod
    def now_str():
        import datetime as _dt
        return _dt.datetime.utcnow().strftime('%d %b %Y %H:%M UTC')
