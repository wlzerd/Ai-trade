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
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            email TEXT UNIQUE,
            password_hash TEXT,
            is_verified INTEGER DEFAULT 0,
            verification_token TEXT
        )
        '''
    )
    conn.commit()
    conn.close()
