from flask import Blueprint, request, jsonify, session
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import db

auth_bp = Blueprint('auth', __name__)
ROLES = ['Admin', 'PP', 'Scrutiny', 'MoM']

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Authentication required'}), 401
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'error': 'Authentication required'}), 401
            user = db.get_user_by_id(session['user_id'])
            if not user or user['role'] not in roles:
                return jsonify({'error': 'Insufficient permissions'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator

def current_user():
    if 'user_id' in session:
        return db.get_user_by_id(session['user_id'])
    return None

def safe_user(u):
    if not u: return None
    return {k: v for k, v in u.items() if k != 'password_hash'}

@auth_bp.route('/register', methods=['POST'])
def register():
    data = request.get_json() or {}
    for k in ['name','email','password','role']:
        if not data.get(k):
            return jsonify({'error': f'Missing field: {k}'}), 400
    if data['role'] not in ROLES:
        return jsonify({'error': f'Role must be one of {ROLES}'}), 400
    if db.get_user_by_email(data['email'].strip().lower()):
        return jsonify({'error': 'Email already registered'}), 409
    if len(data['password']) < 6:
        return jsonify({'error': 'Password must be at least 6 characters'}), 400
    user = db.create_user(
        name=data['name'].strip(),
        email=data['email'].strip().lower(),
        password_hash=generate_password_hash(data['password']),
        role=data['role'],
        department=data.get('department',''),
        phone=data.get('phone','')
    )
    return jsonify({'message':'Registration successful','user':safe_user(user)}), 201

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    user = db.get_user_by_email((data.get('email') or '').strip().lower())
    if not user or not check_password_hash(user['password_hash'], data.get('password','')):
        return jsonify({'error': 'Invalid email or password'}), 401
    session['user_id'] = user['id']
    session['role'] = user['role']
    db.log_audit(user['id'],'LOGIN','system','',request.remote_addr)
    return jsonify({'message':'Login successful','user':safe_user(user)})

@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    u = current_user()
    if u: db.log_audit(u['id'],'LOGOUT','system','',request.remote_addr)
    session.clear()
    return jsonify({'message':'Logged out'})

@auth_bp.route('/me', methods=['GET'])
@login_required
def me():
    return jsonify(safe_user(current_user()))

@auth_bp.route('/users', methods=['GET'])
@login_required
@role_required('Admin')
def list_users():
    return jsonify([safe_user(u) for u in db.get_all_users()])

@auth_bp.route('/users/<int:uid>/role', methods=['PATCH'])
@login_required
@role_required('Admin')
def update_role(uid):
    data = request.get_json() or {}
    if data.get('role') not in ROLES:
        return jsonify({'error': 'Invalid role'}), 400
    user = db.update_user_role(uid, data['role'], data.get('department',''), data.get('phone',''))
    if not user: return jsonify({'error': 'User not found'}), 404
    db.log_audit(session['user_id'],'UPDATE_ROLE',f'user:{uid}',f"role={data['role']}",request.remote_addr)
    return jsonify(safe_user(user))
