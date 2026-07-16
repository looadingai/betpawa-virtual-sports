"""
Database layer — SQLite for Render deployment with persistent disk
"""
import os
import sqlite3
from flask import g

if 'RENDER' in os.environ:
    DATA_DIR = '/opt/render/project/src/data'
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

os.makedirs(DATA_DIR, exist_ok=True)
SQLITE_PATH = os.path.join(DATA_DIR, 'betpawa.db')

def get_db():
    if 'db' not in g:
        conn = sqlite3.connect(SQLITE_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        g.db = conn
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db:
        db.close()

def query(sql, params=(), one=False):
    db = get_db()
    cur = db.execute(sql, params)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def execute(sql, params=()):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    last_id = cur.lastrowid
    cur.close()
    return last_id

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    phone TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    balance REAL DEFAULT 0.0,
    role TEXT DEFAULT 'user',
    created_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1,
    withdrawal_fee REAL DEFAULT 0.0
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT DEFAULT 'pending',
    reference TEXT,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS matchdays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    matchday_number INTEGER NOT NULL,
    league TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    status TEXT DEFAULT 'upcoming',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    matchday_id INTEGER NOT NULL,
    home_code TEXT NOT NULL,
    away_code TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    league TEXT NOT NULL,
    home_score INTEGER DEFAULT 0,
    away_score INTEGER DEFAULT 0,
    ht_home INTEGER DEFAULT 0,
    ht_away INTEGER DEFAULT 0,
    status TEXT DEFAULT 'upcoming',
    current_minute INTEGER DEFAULT 0,
    kickoff_time TEXT,
    preset_home INTEGER DEFAULT NULL,
    preset_away INTEGER DEFAULT NULL,
    odds_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(matchday_id) REFERENCES matchdays(id)
);

CREATE TABLE IF NOT EXISTS match_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL,
    minute INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT,
    team TEXT,
    is_home INTEGER DEFAULT 1,
    FOREIGN KEY(match_id) REFERENCES matches(id)
);

CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    total_stake REAL NOT NULL,
    potential_win REAL NOT NULL,
    status TEXT DEFAULT 'pending',
    placed_at TEXT DEFAULT (datetime('now')),
    settled_at TEXT,
    share_code TEXT UNIQUE,
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS bet_selections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bet_id INTEGER NOT NULL,
    match_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    odds REAL NOT NULL,
    result TEXT DEFAULT 'pending',
    FOREIGN KEY(bet_id) REFERENCES bets(id),
    FOREIGN KEY(match_id) REFERENCES matches(id)
);

CREATE TABLE IF NOT EXISTS admin_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    admin_id INTEGER,
    action TEXT NOT NULL,
    details TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    sender TEXT NOT NULL CHECK(sender IN ('user','admin')),
    message TEXT NOT NULL,
    is_read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS match_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER,
    matchday_id INTEGER,
    league TEXT,
    home_code TEXT,
    away_code TEXT,
    home_team TEXT,
    away_team TEXT,
    home_score INTEGER,
    away_score INTEGER,
    preset_home INTEGER,
    preset_away INTEGER,
    finished_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Chama groups table
CREATE TABLE IF NOT EXISTS chama_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    leader_id INTEGER NOT NULL,
    contribution_amount REAL NOT NULL,
    contribution_frequency TEXT DEFAULT 'weekly',
    payout_cycle TEXT DEFAULT 'monthly',
    interest_rate REAL DEFAULT 0.0,
    total_balance REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now')),
    is_active INTEGER DEFAULT 1,
    share_code TEXT UNIQUE,
    FOREIGN KEY(leader_id) REFERENCES users(id)
);

-- Chama members table
CREATE TABLE IF NOT EXISTS chama_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    joined_at TEXT DEFAULT (datetime('now')),
    total_contributed REAL DEFAULT 0.0,
    total_withdrawn REAL DEFAULT 0.0,
    current_balance REAL DEFAULT 0.0,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY(group_id) REFERENCES chama_groups(id),
    FOREIGN KEY(user_id) REFERENCES users(id),
    UNIQUE(group_id, user_id)
);

-- Chama loans table
CREATE TABLE IF NOT EXISTS chama_loans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    interest_rate REAL DEFAULT 5.0,
    repaid_amount REAL DEFAULT 0.0,
    status TEXT DEFAULT 'pending',
    approved_by INTEGER,
    approved_at TEXT,
    due_date TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(group_id) REFERENCES chama_groups(id),
    FOREIGN KEY(member_id) REFERENCES users(id),
    FOREIGN KEY(approved_by) REFERENCES users(id)
);

-- Chama contributions table
CREATE TABLE IF NOT EXISTS chama_contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    payment_method TEXT DEFAULT 'mpesa',
    transaction_ref TEXT UNIQUE,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(group_id) REFERENCES chama_groups(id),
    FOREIGN KEY(member_id) REFERENCES users(id)
);

-- Chama payouts table
CREATE TABLE IF NOT EXISTS chama_payouts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    status TEXT DEFAULT 'pending',
    processed_by INTEGER,
    processed_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(group_id) REFERENCES chama_groups(id),
    FOREIGN KEY(member_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_bets_user_id ON bets(user_id);
CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status);
CREATE INDEX IF NOT EXISTS idx_bets_share_code ON bets(share_code);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
CREATE INDEX IF NOT EXISTS idx_matches_matchday_id ON matches(matchday_id);
CREATE INDEX IF NOT EXISTS idx_transactions_user_id ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_admin_logs_timestamp ON admin_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_chat_user_id ON chat_messages(user_id);
"""

def init_db(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        db = get_db()
        db.executescript(SCHEMA_SQLITE)
        # Migration: add withdrawal_fee column if not exists
        try:
            db.execute("ALTER TABLE users ADD COLUMN withdrawal_fee REAL DEFAULT 0.0")
            db.commit()
        except:
            pass
        # Migration: add share_code column if not exists
        try:
            db.execute("ALTER TABLE bets ADD COLUMN share_code TEXT UNIQUE")
            db.commit()
        except:
            pass
        db.commit()
        print("✅ Database tables created/verified")
