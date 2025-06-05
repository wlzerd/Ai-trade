from functools import wraps
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

bp = Blueprint('auth', __name__)

login_template = """
<!doctype html>
<title>Login</title>
<h1>Login</h1>
<form method="post">
    <input name="username" placeholder="Username" />
    <input name="password" type="password" placeholder="Password" />
    <button type="submit">Login</button>
</form>
{% if message %}<p style='color:red;'>{{ message }}</p>{% endif %}
<p><a href="{{ url_for('auth.register') }}">Register</a></p>
"""

register_template = """
<!doctype html>
<title>Register</title>
<h1>Register</h1>
<form method="post">
    <input name="username" placeholder="Username" />
    <input name="password" type="password" placeholder="Password" />
    <button type="submit">Register</button>
</form>
{% if message %}<p style='color:red;'>{{ message }}</p>{% endif %}
<p><a href="{{ url_for('auth.login') }}">Login</a></p>
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
            session.clear()
            session['user_id'] = user['id']
            return redirect(url_for('stocks.index'))
        else:
            message = 'Invalid credentials.'
    return render_template_string(login_template, message=message)


@bp.route('/register', methods=['GET', 'POST'])
def register():
    message = None
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if not username or not password:
            message = 'Username and password required.'
        else:
            conn = get_db()
            try:
                conn.execute(
                    'INSERT INTO users (username, password_hash) VALUES (?, ?)',
                    (username, generate_password_hash(password)),
                )
                conn.commit()
                conn.close()
                return redirect(url_for('auth.login'))
            except Exception:
                conn.close()
                message = 'Username already exists.'
    return render_template_string(register_template, message=message)


@bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
