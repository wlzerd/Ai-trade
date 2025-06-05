import sqlite3

DB_PATH = 'stocks.db'


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute(
        'CREATE TABLE IF NOT EXISTS tickers (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT UNIQUE)'
    )

    # check if the users table exists
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if table is None:
        conn.execute(
            '''
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE,
                email TEXT UNIQUE,
                password_hash TEXT,
                is_verified INTEGER DEFAULT 0,
                verification_token TEXT
            )
            '''
        )
    else:
        # upgrade existing table with missing columns
        cols = {row['name'] for row in conn.execute('PRAGMA table_info(users)')}
        if 'email' not in cols:
            conn.execute('ALTER TABLE users ADD COLUMN email TEXT UNIQUE')
        if 'is_verified' not in cols:
            conn.execute('ALTER TABLE users ADD COLUMN is_verified INTEGER DEFAULT 0')
        if 'verification_token' not in cols:
            conn.execute('ALTER TABLE users ADD COLUMN verification_token TEXT')
    conn.commit()
    conn.close()
