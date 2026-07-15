"""Company accounts: login + password, sessions, brute-force throttling.

An ACCOUNT is a company credential, not a person: one login/password may be
shared by several people at that company. Passwords are never stored in clear
text - only a PBKDF2-SHA256 hash (stdlib only, no extra dependency).

Auth precedence lives in web/context.py: if at least one account exists the web
UI requires login+password; if none exist it falls back to the old web.token so
an existing install is never locked out.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time

ALGO = "pbkdf2_sha256"
ITERATIONS = 240_000
SESSION_DAYS = 30
MAX_FAILS = 10          # failed logins from one IP ...
LOCK_WINDOW = 900       # ... within this many seconds -> locked out


# ---------------------------------------------------------------- passwords

def hash_password(password, iterations=ITERATIONS):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"), salt, iterations)
    return f"{ALGO}${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password, encoded):
    try:
        algo, iters, salt_hex, hash_hex = (encoded or "").split("$")
        if algo != ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iters))
    except Exception:
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


def _norm(login):
    return (login or "").strip().lower()


# ---------------------------------------------------------------- accounts

def count(conn):
    return conn.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]


def get(conn, login):
    return conn.execute("SELECT * FROM accounts WHERE login=?", (_norm(login),)).fetchone()


def list_all(conn):
    return conn.execute("SELECT * FROM accounts ORDER BY login").fetchall()


def create(conn, login, password, company=""):
    login = _norm(login)
    if not login:
        raise ValueError("login is required")
    if len(password or "") < 8:
        raise ValueError("password must be at least 8 characters")
    if get(conn, login):
        raise ValueError(f"account '{login}' already exists")
    conn.execute("INSERT INTO accounts(login,password_hash,company,active,created_at)"
                 " VALUES(?,?,?,1,?)",
                 (login, hash_password(password), company or "", time.time()))
    conn.commit()
    return get(conn, login)


def set_password(conn, login, password):
    if len(password or "") < 8:
        raise ValueError("password must be at least 8 characters")
    cur = conn.execute("UPDATE accounts SET password_hash=? WHERE login=?",
                       (hash_password(password), _norm(login)))
    conn.commit()
    if not cur.rowcount:
        raise ValueError(f"no such account '{login}'")
    # a password change invalidates existing sessions
    end_all_sessions(conn, get(conn, login)["id"])


def set_active(conn, login, active):
    cur = conn.execute("UPDATE accounts SET active=? WHERE login=?",
                       (1 if active else 0, _norm(login)))
    conn.commit()
    if not cur.rowcount:
        raise ValueError(f"no such account '{login}'")
    if not active:
        row = get(conn, login)
        if row:
            end_all_sessions(conn, row["id"])


def delete(conn, login):
    row = get(conn, login)
    if not row:
        raise ValueError(f"no such account '{login}'")
    end_all_sessions(conn, row["id"])
    conn.execute("DELETE FROM accounts WHERE id=?", (row["id"],))
    conn.commit()


def authenticate(conn, login, password):
    row = get(conn, login)
    if not row or not row["active"]:
        # still burn the same work so a wrong login is not measurably faster
        verify_password(password, hash_password("dummy"))
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    conn.execute("UPDATE accounts SET last_login_at=? WHERE id=?", (time.time(), row["id"]))
    conn.commit()
    return row


# ---------------------------------------------------------------- sessions

def new_session(conn, account_id, days=SESSION_DAYS):
    sid = secrets.token_urlsafe(32)
    now = time.time()
    conn.execute("INSERT INTO sessions(sid,account_id,created_at,expires_at) VALUES(?,?,?,?)",
                 (sid, account_id, now, now + days * 86400))
    conn.commit()
    return sid


def session_account(conn, sid):
    if not sid:
        return None
    row = conn.execute(
        "SELECT a.* FROM sessions s JOIN accounts a ON a.id = s.account_id "
        "WHERE s.sid=? AND s.expires_at > ? AND a.active=1", (sid, time.time())).fetchone()
    return row


def end_session(conn, sid):
    conn.execute("DELETE FROM sessions WHERE sid=?", (sid,))
    conn.commit()


def end_all_sessions(conn, account_id):
    conn.execute("DELETE FROM sessions WHERE account_id=?", (account_id,))
    conn.commit()


def purge_sessions(conn):
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))
    conn.commit()


# ---------------------------------------------------------------- throttling

def record_attempt(conn, ip, ok):
    if ok:
        clear_attempts(conn, ip)
        return
    conn.execute("INSERT INTO login_attempts(ip,at) VALUES(?,?)", (ip or "?", time.time()))
    conn.commit()


def failures(conn, ip, window=LOCK_WINDOW):
    return conn.execute("SELECT COUNT(*) FROM login_attempts WHERE ip=? AND at > ?",
                        (ip or "?", time.time() - window)).fetchone()[0]


def is_locked(conn, ip, window=LOCK_WINDOW, max_fails=MAX_FAILS):
    return failures(conn, ip, window) >= max_fails


def clear_attempts(conn, ip):
    conn.execute("DELETE FROM login_attempts WHERE ip=?", (ip or "?",))
    conn.commit()
