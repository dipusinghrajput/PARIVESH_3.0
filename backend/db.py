"""
db.py — SQLite data layer for PARIVESH 3.0 (upgraded)
Zero external dependencies beyond Python stdlib.
"""
import sqlite3, os, uuid
from datetime import datetime

DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'parivesh.db'))

VALID_STATUSES = [
    'Draft','Submitted','AIScreening','Scrutiny','EDS',
    'Resubmitted','Referred','MoMGenerated','Finalized'
]

STATUS_TRANSITIONS = {
    'Draft':        ['Submitted'],
    'Submitted':    ['AIScreening'],
    'AIScreening':  ['Scrutiny','EDS'],
    'Scrutiny':     ['EDS','Referred'],
    'EDS':          ['Resubmitted'],
    'Resubmitted':  ['Scrutiny','Referred'],
    'Referred':     ['MoMGenerated'],
    'MoMGenerated': ['Finalized'],
    'Finalized':    []
}

# ── SECTOR DOCUMENT CHECKLISTS ───────────────────────────────────────────────
SECTOR_CHECKLISTS = {
    'Sand Mining': {
        'mandatory': ['Processing Fee Details','Pre-Feasibility Report','District Survey Report (DSR)',
                      'KML File / Survey Map','Gram Panchayat NOC','Forest NOC','Affidavit – Environmental Compliance',
                      'Environmental Management Plan (EMP)'],
        'optional':  ['Drone Video / Site Photos','CER Details','Plantation Commitment']
    },
    'Limestone Mining': {
        'mandatory': ['Processing Fee Details','Pre-Feasibility Report','Mining Plan (CMPDIL Approved)',
                      'Forest NOC','Land Documents','Affidavit – Mining Safety','EMP','KML File'],
        'optional':  ['District Survey Report','Hydrology Report','Blast Management Plan']
    },
    'Brick Kiln': {
        'mandatory': ['Processing Fee Details','Land Documents','Pollution Control Board NOC',
                      'Affidavit – Environmental Compliance','EMP','Site Location Map'],
        'optional':  ['Stack Emission Data','CER Details']
    },
    'Infrastructure': {
        'mandatory': ['Pre-Feasibility Report','EMP','Land Acquisition Details',
                      'Site Location Map','Affidavit – Environmental Compliance','Processing Fee Details'],
        'optional':  ['Forest NOC','Heritage Impact Assessment','Traffic Impact Study']
    },
    'Industry': {
        'mandatory': ['Pre-Feasibility Report','EMP','Pollution Control Board NOC',
                      'Land Documents','Affidavit – Environmental Compliance','Processing Fee Details',
                      'Risk Assessment Report'],
        'optional':  ['Stack Emission Data','Effluent Treatment Plan','CER Details']
    },
    'Energy': {
        'mandatory': ['Pre-Feasibility Report','EMP','Land Documents',
                      'Affidavit – Environmental Compliance','Processing Fee Details','Grid Connectivity Certificate'],
        'optional':  ['Forest NOC','Biodiversity Impact Study','CER Details']
    },
    'Coastal': {
        'mandatory': ['Pre-Feasibility Report','EMP','CRZ Map','Affidavit – CRZ Compliance',
                      'Processing Fee Details','Coastal Zone Management Plan'],
        'optional':  ['Marine Ecology Report','Fisherman Impact Study']
    },
    'Other': {
        'mandatory': ['Pre-Feasibility Report','EMP','Affidavit – Environmental Compliance',
                      'Processing Fee Details'],
        'optional':  ['Additional Supporting Documents']
    }
}

AFFIDAVIT_TYPES = [
    'Affidavit – Environmental Compliance',
    'Affidavit – Mining Safety',
    'Affidavit – CRZ Compliance',
    'Affidavit – Supreme Court Guidelines',
    'Affidavit – Plantation Commitment',
    'Affidavit – Pollution Control'
]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT NOT NULL,
        email         TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role          TEXT NOT NULL DEFAULT 'PP',
        department    TEXT DEFAULT '',
        created_at    TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS applications (
        id               TEXT PRIMARY KEY,
        project_name     TEXT NOT NULL,
        sector           TEXT NOT NULL,
        category         TEXT NOT NULL,
        location         TEXT NOT NULL,
        description      TEXT DEFAULT '',
        capacity         TEXT DEFAULT '',
        area_ha          TEXT DEFAULT '',
        status           TEXT DEFAULT 'Draft',
        ai_score         INTEGER DEFAULT 0,
        ai_report        TEXT DEFAULT '',
        created_by       INTEGER NOT NULL REFERENCES users(id),
        created_at       TEXT DEFAULT (datetime('now')),
        updated_at       TEXT DEFAULT (datetime('now')),
        assigned_officer INTEGER REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS documents (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id      TEXT NOT NULL REFERENCES applications(id),
        document_type       TEXT DEFAULT '',
        original_name       TEXT DEFAULT '',
        file_path           TEXT DEFAULT '',
        version             INTEGER DEFAULT 1,
        uploaded_by         INTEGER REFERENCES users(id),
        uploaded_at         TEXT DEFAULT (datetime('now')),
        previous_version_id INTEGER REFERENCES documents(id),
        is_affidavit        INTEGER DEFAULT 0,
        affidavit_type      TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS timeline_events (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id     TEXT NOT NULL REFERENCES applications(id),
        datetime           TEXT DEFAULT (datetime('now')),
        department         TEXT DEFAULT '',
        actor_id           INTEGER REFERENCES users(id),
        actor_name         TEXT DEFAULT '',
        event_type         TEXT DEFAULT '',
        message            TEXT DEFAULT '',
        status_after_event TEXT DEFAULT '',
        attachment_id      INTEGER REFERENCES documents(id),
        ai_generated       INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id        INTEGER NOT NULL REFERENCES users(id),
        application_id TEXT REFERENCES applications(id),
        title          TEXT DEFAULT '',
        message        TEXT DEFAULT '',
        is_read        INTEGER DEFAULT 0,
        created_at     TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS meetings (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        application_id TEXT REFERENCES applications(id),
        title          TEXT DEFAULT '',
        scheduled_date TEXT DEFAULT '',
        agenda         TEXT DEFAULT '',
        notes          TEXT DEFAULT '',
        gist_text      TEXT DEFAULT '',
        mom_doc_id     INTEGER REFERENCES documents(id),
        status         TEXT DEFAULT 'Scheduled',
        created_by     INTEGER REFERENCES users(id),
        created_at     TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id    INTEGER REFERENCES users(id),
        action     TEXT DEFAULT '',
        target     TEXT DEFAULT '',
        details    TEXT DEFAULT '',
        ip_address TEXT DEFAULT '',
        timestamp  TEXT DEFAULT (datetime('now'))
    );
    """)
    conn.commit()
    conn.close()


def row_to_dict(row):
    return dict(row) if row else None

def rows_to_list(rows):
    return [dict(r) for r in rows]


# ── USERS ────────────────────────────────────────────────────────────────────
def create_user(name, email, password_hash, role, department=''):
    conn = get_conn()
    conn.execute("INSERT INTO users (name,email,password_hash,role,department) VALUES (?,?,?,?,?)",
                 (name, email, password_hash, role, department))
    conn.commit()
    conn.close()
    return get_user_by_email(email)

def get_user_by_id(uid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close(); return row_to_dict(row)

def get_user_by_email(email):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    conn.close(); return row_to_dict(row)

def get_all_users():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    conn.close(); return rows_to_list(rows)

def update_user_role(uid, role, department):
    conn = get_conn()
    conn.execute("UPDATE users SET role=?,department=? WHERE id=?", (role, department, uid))
    conn.commit(); conn.close()
    return get_user_by_id(uid)


# ── APPLICATIONS ─────────────────────────────────────────────────────────────
def create_application(project_name, sector, category, location, description,
                        created_by, capacity='', area_ha=''):
    app_id = 'EC-' + str(uuid.uuid4())[:8].upper()
    conn = get_conn()
    conn.execute("""INSERT INTO applications
        (id,project_name,sector,category,location,description,capacity,area_ha,status,created_by)
        VALUES (?,?,?,?,?,?,?,?,'Draft',?)""",
        (app_id, project_name, sector, category, location, description, capacity, area_ha, created_by))
    conn.commit(); conn.close()
    return get_application(app_id)

def get_application(app_id):
    conn = get_conn()
    row = conn.execute("""
        SELECT a.*, u1.name AS creator_name, u1.email AS creator_email,
               u2.name AS officer_name, u2.department AS officer_dept
        FROM applications a
        LEFT JOIN users u1 ON a.created_by=u1.id
        LEFT JOIN users u2 ON a.assigned_officer=u2.id
        WHERE a.id=?""", (app_id,)).fetchone()
    conn.close(); return row_to_dict(row)

def list_applications(user_id=None, role=None, status=None, sector=None, search=None):
    conn = get_conn()
    sql = """SELECT a.*, u1.name AS creator_name,
                    u2.name AS officer_name, u2.department AS officer_dept
             FROM applications a
             LEFT JOIN users u1 ON a.created_by=u1.id
             LEFT JOIN users u2 ON a.assigned_officer=u2.id WHERE 1=1"""
    params = []
    if role == 'PP' and user_id:
        sql += " AND a.created_by=?"; params.append(user_id)
    if status:
        sql += " AND a.status=?"; params.append(status)
    if sector:
        sql += " AND a.sector=?"; params.append(sector)
    if search:
        s = f'%{search}%'
        sql += " AND (a.id LIKE ? OR a.project_name LIKE ? OR a.location LIKE ? OR u1.name LIKE ?)"
        params.extend([s,s,s,s])
    sql += " ORDER BY a.created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close(); return rows_to_list(rows)

def update_application(app_id, **kwargs):
    if not kwargs: return
    fields = ', '.join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [app_id]
    conn = get_conn()
    conn.execute(f"UPDATE applications SET {fields}, updated_at=datetime('now') WHERE id=?", vals)
    conn.commit(); conn.close()


# ── DOCUMENTS ─────────────────────────────────────────────────────────────────
def create_document(application_id, document_type, original_name, file_path,
                     version, uploaded_by, previous_version_id=None,
                     is_affidavit=0, affidavit_type=''):
    conn = get_conn()
    cur = conn.execute("""INSERT INTO documents
        (application_id,document_type,original_name,file_path,version,uploaded_by,
         previous_version_id,is_affidavit,affidavit_type)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (application_id, document_type, original_name, file_path, version,
         uploaded_by, previous_version_id, is_affidavit, affidavit_type))
    doc_id = cur.lastrowid; conn.commit(); conn.close()
    return get_document(doc_id)

def get_document(doc_id):
    conn = get_conn()
    row = conn.execute("""SELECT d.*, u.name AS uploader_name
        FROM documents d LEFT JOIN users u ON d.uploaded_by=u.id WHERE d.id=?""", (doc_id,)).fetchone()
    conn.close(); return row_to_dict(row)

def get_documents_for_app(app_id):
    conn = get_conn()
    rows = conn.execute("""SELECT d.*, u.name AS uploader_name
        FROM documents d LEFT JOIN users u ON d.uploaded_by=u.id
        WHERE d.application_id=? ORDER BY d.uploaded_at DESC""", (app_id,)).fetchall()
    conn.close(); return rows_to_list(rows)


# ── TIMELINE ─────────────────────────────────────────────────────────────────
def create_event(application_id, actor_id, actor_name, department,
                  event_type, message, status_after_event,
                  attachment_id=None, ai_generated=0):
    conn = get_conn()
    cur = conn.execute("""INSERT INTO timeline_events
        (application_id,actor_id,actor_name,department,event_type,message,
         status_after_event,attachment_id,ai_generated)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (application_id, actor_id, actor_name, department, event_type,
         message, status_after_event, attachment_id, ai_generated))
    eid = cur.lastrowid; conn.commit(); conn.close()
    return get_event(eid)

def get_event(eid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM timeline_events WHERE id=?", (eid,)).fetchone()
    conn.close(); return row_to_dict(row)

def get_timeline(app_id, event_type_filter=None):
    conn = get_conn()
    if event_type_filter:
        types = event_type_filter.split(',')
        ph = ','.join('?'*len(types))
        rows = conn.execute(
            f"SELECT * FROM timeline_events WHERE application_id=? AND event_type IN ({ph}) ORDER BY datetime ASC",
            [app_id]+types).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM timeline_events WHERE application_id=? ORDER BY datetime ASC", (app_id,)).fetchall()
    events = []
    for row in rows:
        ev = dict(row)
        if ev.get('attachment_id'):
            doc = get_document(ev['attachment_id'])
            if doc:
                prev = get_document(doc['previous_version_id']) if doc.get('previous_version_id') else None
                ev['attachment'] = {
                    'id': doc['id'], 'document_type': doc['document_type'],
                    'file_path': doc['file_path'], 'version': doc['version'],
                    'original_name': doc['original_name'],
                    'prev_version_id': doc['previous_version_id'],
                    'prev_original_name': prev['original_name'] if prev else None,
                    'prev_version': prev['version'] if prev else None,
                    'prev_id': prev['id'] if prev else None,
                }
            else: ev['attachment'] = None
        else: ev['attachment'] = None
        events.append(ev)
    conn.close(); return events


# ── NOTIFICATIONS ─────────────────────────────────────────────────────────────
def create_notification(user_id, application_id, title, message):
    conn = get_conn()
    conn.execute("INSERT INTO notifications (user_id,application_id,title,message) VALUES (?,?,?,?)",
                 (user_id, application_id, title, message))
    conn.commit(); conn.close()

def get_notifications(user_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50", (user_id,)).fetchall()
    conn.close(); return rows_to_list(rows)

def mark_all_read(user_id):
    conn = get_conn()
    conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0", (user_id,))
    conn.commit(); conn.close()

def notify_role(role, application_id, title, message):
    conn = get_conn()
    users = conn.execute("SELECT id FROM users WHERE role=?", (role,)).fetchall()
    conn.close()
    for u in users: create_notification(u['id'], application_id, title, message)


# ── MEETINGS ─────────────────────────────────────────────────────────────────
def create_meeting(application_id, title, scheduled_date, agenda, created_by, gist_text=''):
    conn = get_conn()
    cur = conn.execute("""INSERT INTO meetings
        (application_id,title,scheduled_date,agenda,gist_text,created_by)
        VALUES (?,?,?,?,?,?)""",
        (application_id, title, scheduled_date, agenda, gist_text, created_by))
    mid = cur.lastrowid; conn.commit(); conn.close()
    return get_meeting(mid)

def get_meeting(mid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM meetings WHERE id=?", (mid,)).fetchone()
    conn.close(); return row_to_dict(row)

def update_meeting(mid, **kwargs):
    if not kwargs: return
    fields = ', '.join(f"{k}=?" for k in kwargs)
    vals = list(kwargs.values()) + [mid]
    conn = get_conn()
    conn.execute(f"UPDATE meetings SET {fields} WHERE id=?", vals)
    conn.commit(); conn.close()

def get_meetings_for_app(app_id):
    conn = get_conn()
    rows = conn.execute("SELECT * FROM meetings WHERE application_id=? ORDER BY scheduled_date DESC", (app_id,)).fetchall()
    conn.close(); return rows_to_list(rows)

def get_all_meetings():
    conn = get_conn()
    rows = conn.execute("""
        SELECT m.*, a.project_name, a.sector
        FROM meetings m LEFT JOIN applications a ON m.application_id=a.id
        ORDER BY m.scheduled_date DESC""").fetchall()
    conn.close(); return rows_to_list(rows)


# ── AUDIT ─────────────────────────────────────────────────────────────────────
def log_audit(user_id, action, target='', details='', ip=''):
    conn = get_conn()
    conn.execute("INSERT INTO audit_logs (user_id,action,target,details,ip_address) VALUES (?,?,?,?,?)",
                 (user_id, action, target, details, ip))
    conn.commit(); conn.close()
