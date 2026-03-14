"""Seed PARIVESH 3.0 with rich demo data. Run: cd backend && python seed.py"""
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
import db
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

if os.path.exists(db.DB_PATH):
    os.remove(db.DB_PATH)
db.init_db()

# ── USERS ─────────────────────────────────────────────────────────────────────
admin    = db.create_user('Admin User',     'admin@parivesh.gov.in',  generate_password_hash('admin123'),  'Admin',    'Ministry of Environment',  '+91-11-2436-0001')
pp1      = db.create_user('Rahul Verma',    'rahul@infra.com',        generate_password_hash('test123'),   'PP',       'InfraBuild Ltd',           '+91-98765-43210')
pp2      = db.create_user('Sunita Patel',   'sunita@mining.com',      generate_password_hash('test123'),   'PP',       'Vindhya Minerals Pvt Ltd', '+91-94321-56789')
scrutiny = db.create_user('Priya Sharma',   'priya@scrutiny.gov.in',  generate_password_hash('test123'),   'Scrutiny', 'Scrutiny Division, MoEFCC', '+91-11-2463-8800')
mom      = db.create_user('Anil Mehta',     'anil@mom.gov.in',        generate_password_hash('test123'),   'MoM',      'MoM Secretariat, MoEFCC',  '+91-11-2463-8900')

def insert_app(app_id, project_name, sector, category, location, description,
               status, created_by, assigned_officer=None, ai_score=0, ai_report='',
               capacity='', area_ha='', days_ago=0):
    c = db.get_conn()
    c.execute("""INSERT INTO applications
        (id,project_name,sector,category,location,description,status,created_by,
         assigned_officer,ai_score,ai_report,capacity,area_ha,
         created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now',?),datetime('now',?))""",
        (app_id, project_name, sector, category, location, description, status,
         created_by, assigned_officer, ai_score, ai_report, capacity, area_ha,
         f'-{days_ago} days', f'-{max(0,days_ago-2)} days'))
    c.commit(); c.close()

def insert_event(app_id, actor_id, actor_name, dept, etype, msg, sat, days_ago=0, hours=0, ai_gen=0):
    c = db.get_conn()
    c.execute("""INSERT INTO timeline_events
        (application_id,datetime,actor_id,actor_name,department,event_type,message,status_after_event,ai_generated)
        VALUES (?,datetime('now',?,?),?,?,?,?,?,?,?)""",
        (app_id, f'-{days_ago} days', f'-{hours} hours',
         actor_id, actor_name, dept, etype, msg, sat, ai_gen))
    c.commit(); c.close()

ai_pass = json.dumps({'score':82,'passed':True,'checks_passed':['All mandatory docs','Affidavit present','Valid file types','Project details complete','EMP found','Fee document found'],'issues':[],'warnings':['KML file not detected'],'suggested_eds_points':[],'recommendation':'PASS — Forward to Scrutiny Queue'})
ai_fail = json.dumps({'score':45,'passed':False,'checks_passed':['Valid file types'],'issues':[{'category':'Missing Mandatory Documents','items':['Forest NOC','District Survey Report (DSR)']},{'category':'Missing Affidavit','items':['No compliance affidavit uploaded']}],'warnings':['Project description too brief'],'suggested_eds_points':['Upload Forest NOC','Upload District Survey Report (DSR)','Upload signed compliance affidavit','Provide detailed project description'],'recommendation':'FAIL — Return EDS to Applicant'})

# ── APP 1: Finalized (Sand Mining) ────────────────────────────────────────────
insert_app('EC-DEMO001','Alaknanda Sand Mining Unit','Sand Mining','B1','Tehri, Uttarakhand',
           'Extraction of river-bed sand from Alaknanda river basin for construction use. Annual capacity 50,000 MT.',
           'Finalized', pp1['id'], None, 91, ai_pass, '50,000 MT/year','12.5', days_ago=35)

for d,h,aid,aname,dept,et,msg,sat,ai in [
    (35,0, pp1['id'], pp1['name'],'Applicant','submission','Application submitted. 6 document(s) uploaded. AI pre-screening initiated.','AIScreening',0),
    (34,22,None,'AI Screening Engine','AI System','ai_screen','✅ AI Pre-Screen PASSED (Score: 91/100)\n6 checks passed. Forwarding to Scrutiny.','Scrutiny',1),
    (32,4, scrutiny['id'],scrutiny['name'],'Scrutiny Division','verification',f'Application assigned to {scrutiny["name"]} for scrutiny review.','Scrutiny',0),
    (28,6, scrutiny['id'],scrutiny['name'],'Scrutiny Division','issue','EDS Raised.\nIssue: Gram Panchayat NOC missing for survey no. 142.\nRequested Document: Gram Panchayat NOC','EDS',0),
    (25,10,pp1['id'],pp1['name'],'Applicant','response','EDS response submitted. Gram Panchayat NOC attached and notarized affidavit updated.','Resubmitted',0),
    (22,8, scrutiny['id'],scrutiny['name'],'Scrutiny Division','verification','All documents verified. Application cleared for EAC referral.','Scrutiny',0),
    (18,6, scrutiny['id'],scrutiny['name'],'Scrutiny Division','meeting','Application referred to Expert Appraisal Committee for deliberation.','Referred',0),
    (12,4, mom['id'],mom['name'],'MoM Secretariat','meeting','Minutes of Meeting generated.\nDiscussion: Committee reviewed sand extraction limits and riverbed impact. Recommends clearance with conditions on seasonal mining ban.','MoMGenerated',0),
    (5,3,  admin['id'],admin['name'],'Ministry','decision','Environmental Clearance GRANTED with conditions:\n1. No extraction June-September (monsoon ban)\n2. Monthly riverbed monitoring reports\n3. Rehabilitation of mined area within 60 days','Finalized',0),
]:
    insert_event('EC-DEMO001',aid,aname,dept,et,msg,sat,d,h,ai)

# ── APP 2: EDS Stage (Limestone) ─────────────────────────────────────────────
insert_app('EC-DEMO002','Vindhya Limestone Quarry Phase 2','Limestone Mining','A','Satna, Madhya Pradesh',
           'Expansion of existing limestone quarry from 2 MTPA to 4 MTPA.',
           'EDS', pp2['id'], scrutiny['id'], 45, ai_fail, '4 MTPA','85', days_ago=10)

for d,h,aid,aname,dept,et,msg,sat,ai in [
    (10,0, pp2['id'],pp2['name'],'Applicant','submission','Application submitted. 3 document(s) uploaded. AI pre-screening initiated.','AIScreening',0),
    (9,23, None,'AI Screening Engine','AI System','ai_screen','❌ AI Pre-Screen FAILED (Score: 45/100)\n\nIssues found:\n• Upload Forest NOC\n• Upload District Survey Report (DSR)\n• Upload signed compliance affidavit\n• Provide detailed project description','EDS',1),
]:
    insert_event('EC-DEMO002',aid,aname,dept,et,msg,sat,d,h,ai)

# ── APP 3: Under Scrutiny (Infrastructure) ────────────────────────────────────
insert_app('EC-DEMO003','Coastal Highway Extension Phase 2','Infrastructure','B1','Raigad, Maharashtra',
           'Construction of 28 km 6-lane coastal highway extension from Alibaug to Rewas ferry point. Involves partial CRZ zone.',
           'Scrutiny', pp1['id'], scrutiny['id'], 78, ai_pass, '28 km highway','—', days_ago=8)

for d,h,aid,aname,dept,et,msg,sat,ai in [
    (8,0,  pp1['id'],pp1['name'],'Applicant','submission','Application submitted. 7 document(s) uploaded. AI pre-screening initiated.','AIScreening',0),
    (7,22, None,'AI Screening Engine','AI System','ai_screen','✅ AI Pre-Screen PASSED (Score: 78/100)\nForwarding to Scrutiny.','Scrutiny',1),
    (6,4,  scrutiny['id'],scrutiny['name'],'Scrutiny Division','verification',f'Application assigned to {scrutiny["name"]}.','Scrutiny',0),
]:
    insert_event('EC-DEMO003',aid,aname,dept,et,msg,sat,d,h,ai)

# ── APP 4: Draft ──────────────────────────────────────────────────────────────
insert_app('EC-DEMO004','Rajasthan Solar Farm 500MW','Energy','A','Jodhpur, Rajasthan',
           'Utility-scale 500 MW solar PV project on government wasteland.',
           'Draft', pp2['id'], None, 0, '', '500 MW','1200', days_ago=2)
insert_event('EC-DEMO004',pp2['id'],pp2['name'],'Applicant','submission','Application created as Draft.','Draft',2,0,0)

# ── MEETING ───────────────────────────────────────────────────────────────────
c = db.get_conn()
c.execute("""INSERT INTO meetings (application_id,title,scheduled_date,agenda,notes,gist_text,status,created_by,created_at)
    VALUES ('EC-DEMO001','EAC Meeting #142 — Sand Mining Cases',
    '2024-03-20',
    '1. EC-DEMO001 Alaknanda Sand Mining\n2. General updates on river mining policy',
    'Committee reviewed extraction limits. Seasonal monsoon ban recommended. All members agreed.',
    'PARIVESH 3.0 GIST — EC-DEMO001\nAlaknanda Sand Mining Unit\nSatna, Uttarakhand\nStatus: Finalized',
    'Completed',?,datetime('now','-12 days'))""", (mom['id'],))
c.commit(); c.close()

# ── NOTIFICATIONS ─────────────────────────────────────────────────────────────
db.create_notification(pp2['id'],'EC-DEMO002','AI Pre-Screen Failed — Action Required',
    'Your application EC-DEMO002 failed AI pre-screening. Upload Forest NOC, DSR, and affidavit.')
db.create_notification(scrutiny['id'],'EC-DEMO003','New Application — AI Cleared',
    'EC-DEMO003 passed AI screening (score 78). Ready for review.')
db.create_notification(pp1['id'],'EC-DEMO001','Environmental Clearance Granted',
    'Congratulations! EC-DEMO001 has been granted Environmental Clearance.')

print("✅ Database seeded with rich demo data!\n")
print("  Credentials:")
print("  Admin:    admin@parivesh.gov.in  / admin123")
print("  PP:       rahul@infra.com        / test123  (Sunita: sunita@mining.com)")
print("  Scrutiny: priya@scrutiny.gov.in  / test123")
print("  MoM:      anil@mom.gov.in        / test123")
