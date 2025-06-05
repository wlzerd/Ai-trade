from flask import Flask
import os

import db
from auth import bp as auth_bp
from stocks import bp as stocks_bp

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24))

app.register_blueprint(auth_bp)
app.register_blueprint(stocks_bp)

db.init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')
