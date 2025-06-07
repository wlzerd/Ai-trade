from functools import wraps
import secrets
import sqlite3
import os
import requests
from dotenv import load_dotenv
from flask import (
    Blueprint,
    request,
    session,
    g,
    redirect,
    url_for,
    render_template_string,
)
load_dotenv()
# Placeholder image used for social previews
OG_IMAGE_URL = os.getenv("LOGO")
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
<meta property=\"og:type\" content=\"website\">
<meta property=\"og:title\" content=\"로그인 | 주식 ai 도구\">
<meta property=\"og:description\" content=\"주식에 대한 정보를 쉽고 간편하게 StockInfoAI으로!\">
<meta property=\"og:url\" content=\"{{ url_for('auth.login', _external=True, _scheme='https') }}\">
<meta property=\"og:image\" content=\"{{ OG_IMAGE_URL }}\">
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
<meta property=\"og:type\" content=\"website\">
<meta property=\"og:title\" content=\"회원가입 | Ai-Trade\">
<meta property=\"og:description\" content=\"Ai-Trade 회원가입 페이지\">
<meta property=\"og:url\" content=\"{{ url_for('auth.register', _external=True) }}\">
<meta property=\"og:image\" content=\"{{ OG_IMAGE_URL }}\">
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
<meta property=\"og:type\" content=\"website\">
<meta property=\"og:title\" content=\"이메일 인증 | Ai-Trade\">
<meta property=\"og:description\" content=\"이메일 인증 안내 페이지\">
<meta property=\"og:url\" content=\"{{ url_for('auth.login', _external=True) }}\">
<meta property=\"og:image\" content=\"{{ OG_IMAGE_URL }}\">
<title>이메일 인증</title>
</head>
<body class=\"container py-5\">
<h1>이메일 인증</h1>
<p>{{ message }}</p>
<p><a class=\"btn btn-primary\" href='{{ url_for('auth.login') }}'>로그인 하러가기</a></p>
</body>
</html>
"""

def send_verification_email(to_email, verify_url):
    """Send a verification email with the given URL."""
    mailgun_key = os.environ.get("MAILGUN_API_KEY")
    mailgun_domain = os.environ.get("MAILGUN_DOMAIN")
    print(mailgun_key, mailgun_domain)
    html_body = f"""
<!doctype html>
<html lang=\"ko\">
<body style=\"font-family:sans-serif;text-align:center;\">
  <h2>회원가입을 축하합니다!</h2>
  <p>아래 버튼을 눌러 이메일 인증을 완료해주세요.</p>
  <a href=\"{verify_url}\" style=\"display:inline-block;padding:10px 20px;background:#1a73e8;color:#fff;text-decoration:none;border-radius:4px;\">이메일 인증하기</a>
</body>
</html>
"""
    if not (mailgun_key and mailgun_domain):
        return False
    sender = os.environ.get("MAILGUN_FROM", f"no-reply@{mailgun_domain}")
    try:
        resp = requests.post(
            f"https://api.mailgun.net/v3/{mailgun_domain}/messages",
            auth=("api", mailgun_key),
            data={
                "from": sender,
                "to": [to_email],
                "subject": "Ai주식거래 사이트 이메일 인증",
                "text": f"다음 링크를 클릭하여 이메일 인증을 완료해주세요: {verify_url}",
                "html": html_body,
            },
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send email via Mailgun: {e}")
        return False

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
    return render_template_string(login_template, message=message,OG_IMAGE_URL=OG_IMAGE_URL)


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
                if send_verification_email(email, verify_url):
                    message = '인증 링크가 이메일로 전송되었습니다.'
                else:
                    message = f'이메일을 보내지 못했습니다. 다음 링크를 방문해 계정을 인증해주세요: {verify_url}'
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
        message = '이메일 인증이 완료되었습니다. 이제 로그인 하실 수 있습니다.'
    else:
        message = '유효하지 않은 인증 토큰입니다.'
    conn.close()
    return render_template_string(verify_template, message=message)

@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
