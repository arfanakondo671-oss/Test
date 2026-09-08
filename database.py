import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "bot.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            points INTEGER DEFAULT 3,
            referred_by INTEGER,
            last_bonus TEXT,
            banned INTEGER DEFAULT 0,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            number TEXT,
            prank_id TEXT,
            uid TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def ensure_user(user_id: int, username: str | None, full_name: str, referred_by: int | None = None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute(
            """
            INSERT INTO users (user_id, username, full_name, points, referred_by, created_at)
            VALUES (?, ?, ?, 3, ?, ?)
            """,
            (user_id, username, full_name, referred_by, datetime.utcnow().isoformat()),
        )
        conn.commit()
        created = True
    else:
        cur.execute(
            "UPDATE users SET username = ?, full_name = ? WHERE user_id = ?",
            (username, full_name, user_id),
        )
        conn.commit()
        created = False
    conn.close()
    return created


def get_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def is_banned(user_id: int) -> bool:
    u = get_user(user_id)
    return bool(u and u["banned"])


def add_points(user_id: int, amount: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET points = points + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


def set_points(user_id: int, amount: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET points = ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()


def claim_bonus(user_id: int, amount: int) -> bool:
    today = date.today().isoformat()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT last_bonus FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False
    if row["last_bonus"] == today:
        conn.close()
        return False
    cur.execute(
        "UPDATE users SET points = points + ?, last_bonus = ? WHERE user_id = ?",
        (amount, today, user_id),
    )
    conn.commit()
    conn.close()
    return True


def set_banned(user_id: int, banned: bool):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET banned = ? WHERE user_id = ?", (1 if banned else 0, user_id))
    conn.commit()
    conn.close()


def save_call(user_id: int, number: str, prank_id: str, uid: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO calls (user_id, number, prank_id, uid, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, number, prank_id, uid, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def user_count() -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM users")
    n = cur.fetchone()["c"]
    conn.close()
    return n
