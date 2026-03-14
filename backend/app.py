import os, sys
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, send_from_directory, jsonify
from dotenv import load_dotenv
import db

load_dotenv()

def create_app():
    base = os.path.dirname(__file__)
    app  = Flask(__name__,
                 static_folder=os.path.join(base,'..','static'),
                 static_url_path='/static')
    app.config['SECRET_KEY']    = os.environ.get('SECRET_KEY','parivesh-dev-secret-2024')
    app.config['UPLOAD_FOLDER'] = os.path.join(base,'..','uploads')
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    db.init_db()

    from routes.auth import auth_bp
    from routes.applications import app_bp
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(app_bp,  url_prefix='/api')

    frontend = os.path.join(base, '..', 'frontend')

    @app.route('/')
    def index(): return send_from_directory(frontend, 'login.html')

    for page in ['login','dashboard','application_form','case_file',
                 'scrutiny','mom','admin','meetings']:
        def _make(p):
            def fn(): return send_from_directory(frontend, f'{p}.html')
            fn.__name__ = f'page_{p}'
            return fn
        app.route(f'/{page}')(_make(page))

    @app.errorhandler(404)
    def e404(e): return jsonify({'error':'Not found'}), 404
    @app.errorhandler(500)
    def e500(e): return jsonify({'error':'Server error'}), 500

    return app

if __name__ == '__main__':
    app = create_app()
    print("\n✅  PARIVESH 3.0 (Upgraded) → http://localhost:5000\n")
    app.run(debug=True, host='0.0.0.0', port=5000)
