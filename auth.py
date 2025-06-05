from functools import wraps
import secrets
import sqlite3
from flask import (
    Blueprint,
    request,
    session,
    g,
    redirect,
    url_for,
    render_template_string,
)
from werkzeug.security import generate_password_hash, check_password_hash

from db import get_db

# Authentication blueprint and templates
bp = Blueprint('auth', __name__)

login_template = """
<!doctype html>
<html lang=\"ko\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
<title>Login</title>
</head>
<body class=\"container py-5\">
<h1>Login</h1>
<form method=\"post\" class=\"mb-3\">
  <div class=\"mb-3\">
    <input class=\"form-control\" name=\"username\" placeholder=\"Username\">
  </div>
  <div class=\"mb-3\">
    <input class=\"form-control\" type=\"password\" name=\"password\" placeholder=\"Password\">
  </div>
  <button class=\"btn btn-primary\" type=\"submit\">Login</button>
</form>
{% if message %}<div class='alert alert-danger'>{{ message }}</div>{% endif %}
<p>Don't have an account? <a href='{{ url_for('auth.register') }}'>Register</a></p>
</body>
</html>
"""

register_template = """
<!doctype html>
<html lang=\"ko\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
<title>Register</title>
</head>
<body class=\"container py-5\">
<h1>Register</h1>
<form method=\"post\" class=\"mb-3\">
  <div class=\"mb-3\">
    <input class=\"form-control\" name=\"username\" placeholder=\"Username\">
  </div>
  <div class=\"mb-3\">
    <input class=\"form-control\" type=\"email\" name=\"email\" placeholder=\"Email\">
  </div>
  <div class=\"mb-3\">
    <input class=\"form-control\" type=\"password\" name=\"password\" placeholder=\"Password\">
  </div>
  <button class=\"btn btn-primary\" type=\"submit\">Register</button>
</form>
{% if message %}<div class='alert alert-danger'>{{ message }}</div>{% endif %}
<p>Already have an account? <a href='{{ url_for('auth.login') }}'>Login</a></p>
</body>
</html>
"""

verify_template = """
<!doctype html>
<html lang=\"ko\">
<head>
<meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
<title>Email Verification</title>
</head>
<body class=\"container py-5\">
<h1>Email Verification</h1>
<p>{{ message }}</p>
<p><a href='{{ url_for('auth.login') }}'>Login</a></p>
</body>
</html>
"""

@bp.before_app_request
def load_logged_in_user():
    user_id = session.get('user_id')
    if user_id is None:
        g.user = None
    else:
        conn = get_db()
        g.user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        conn.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get('user') is None:
            return redirect(url_for('auth.login'))
        return view(*args, **kwargs)

    return wrapped


@bp.route('/login', methods=['GET', 'POST'])
def login():
    message = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user['password_hash'], password):
            if not user['is_verified']:
                message = '로그인 하기 전에 이메일 인증을 완료해주세요.'
            else:
                session.clear()
                session['user_id'] = user['id']
                return redirect(url_for('stocks.index'))
        else:
            message = '잘못된 사용자 이름 또는 비밀번호입니다.'
    return render_template_string(login_template, message=message)


@bp.route('/register', methods=['GET', 'POST'])
def register():
    message = None
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        if not username or not password or not email:
            message = '사용자 이름, 이메일, 비밀번호를 모두 입력해야 합니다.'
        else:
            conn = get_db()
            try:
                token = secrets.token_urlsafe(16)
                conn.execute(
                    'INSERT INTO users (username, email, password_hash, verification_token) VALUES (?, ?, ?, ?)',
                    (username, email, generate_password_hash(password), token),
                )
                conn.commit()
                verify_url = url_for('auth.verify', token=token, _external=True)
                message = f'Check your email and visit {verify_url} to verify your account.'
                return render_template_string(verify_template, message=message)
            except sqlite3.IntegrityError:
                message = '이미 사용 중인 사용자 이름 또는 이메일입니다.'
            finally:
                conn.close()
    return render_template_string(register_template, message=message)


@bp.route('/verify/<token>')
def verify(token):
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE verification_token = ?', (token,)).fetchone()
    if user:
        conn.execute(
            'UPDATE users SET is_verified = 1, verification_token = NULL WHERE id = ?',
            (user['id'],),
        )
        conn.commit()
        message = 'Email verified. You can now log in.'
    else:
        message = '유효하지 않은 인증 토큰입니다.'
    conn.close()
    return render_template_string(verify_template, message=message)

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
