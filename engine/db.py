from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    payload_json TEXT,
    UNIQUE(source, external_id, content_hash)
);

CREATE TABLE IF NOT EXISTS tenders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    normalized_json TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL UNIQUE,
    pipeline TEXT NOT NULL,
    mode TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    started_at REAL NOT NULL,
    finished_at REAL
);

CREATE TABLE IF NOT EXISTS stage_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    tender_id INTEGER,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL,
    input_hash TEXT,
    started_at REAL NOT NULL,
    finished_at REAL,
    tokens INTEGER DEFAULT 0,
    cost REAL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS stage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    seq INTEGER NOT NULL,
    label TEXT,
    detail TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stage_events ON stage_events(tender_id, stage);

CREATE TABLE IF NOT EXISTS verdicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id INTEGER,
    stage_name TEXT NOT NULL,
    verdict TEXT,
    score REAL,
    confidence REAL,
    reason TEXT,
    model TEXT,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    version INTEGER NOT NULL,
    value_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    actor TEXT,
    created_at REAL NOT NULL,
    UNIQUE(key, version)
);

CREATE TABLE IF NOT EXISTS config_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    actor TEXT,
    action TEXT NOT NULL,
    entity TEXT,
    detail_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_stage_runs_run ON stage_runs(run_id);
CREATE INDEX IF NOT EXISTS idx_verdicts_tender ON verdicts(tender_id);
CREATE INDEX IF NOT EXISTS idx_configs_key_active ON configs(key, active);
"""


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


SCHEMA_ACCOUNTS = """
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    company TEXT,
    role TEXT NOT NULL DEFAULT 'user',
    active INTEGER NOT NULL DEFAULT 1,
    created_at REAL,
    last_login_at REAL
);
CREATE TABLE IF NOT EXISTS sessions (
    sid TEXT PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    created_at REAL,
    expires_at REAL
);
CREATE INDEX IF NOT EXISTS idx_sessions_account ON sessions(account_id);
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT,
    at REAL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_ip ON login_attempts(ip, at);
"""

SCHEMA_WORK = """
CREATE TABLE IF NOT EXISTS tender_work (
    tender_id INTEGER NOT NULL REFERENCES tenders(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT 'qualified',
    note TEXT,
    updated_at REAL,
    PRIMARY KEY (tender_id, account_id)
);
CREATE INDEX IF NOT EXISTS idx_tender_work_stage ON tender_work(account_id, stage);
CREATE TABLE IF NOT EXISTS account_settings (
    account_id INTEGER NOT NULL,
    key TEXT NOT NULL,
    value TEXT,
    updated_at REAL,
    PRIMARY KEY (account_id, key)
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executescript(SCHEMA_SOURCES)
    conn.executescript(SCHEMA_LLM)
    conn.executescript(SCHEMA_EXTRACT)
    conn.executescript(SCHEMA_VERIFY)
    conn.executescript(SCHEMA_SUPPLIERS)
    conn.executescript(SCHEMA_SUPERVISOR)
    conn.executescript(SCHEMA_ACCOUNTS)
    conn.executescript(SCHEMA_WORK)
    _migrate(conn)
    row = conn.execute(
        "SELECT value FROM config_meta WHERE key='generation'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO config_meta(key, value) VALUES('generation', '0')"
        )
    conn.commit()


SCHEMA_SOURCES = """
CREATE TABLE IF NOT EXISTS source_state (
    source TEXT PRIMARY KEY,
    cursor TEXT,
    last_count INTEGER DEFAULT 0,
    last_run_at REAL
);

CREATE TABLE IF NOT EXISTS source_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    started_at REAL NOT NULL,
    finished_at REAL,
    fetched INTEGER DEFAULT 0,
    new_items INTEGER DEFAULT 0,
    cursor_before TEXT,
    cursor_after TEXT,
    status TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_runs_source ON source_runs(source);

CREATE TABLE IF NOT EXISTS crawl_state (
    site_id TEXT PRIMARY KEY,
    next_url TEXT,
    auth_json TEXT,
    last_run_at REAL,
    total_collected INTEGER DEFAULT 0,
    exhausted INTEGER DEFAULT 0,
    total_estimate INTEGER,
    note TEXT,
    detected_count INTEGER,
    page_hash TEXT
);

CREATE TABLE IF NOT EXISTS dismissed_tenders (
    external_id TEXT PRIMARY KEY,
    source TEXT,
    reason TEXT,
    dismissed_at REAL
);
"""


SCHEMA_LLM = """
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    model TEXT,
    response_json TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    created_at REAL
);
"""


SCHEMA_EXTRACT = """
CREATE TABLE IF NOT EXISTS extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id INTEGER NOT NULL,
    fields_json TEXT,
    sources_json TEXT,
    model TEXT,
    method TEXT,
    tokens INTEGER DEFAULT 0,
    cost REAL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_extractions_tender ON extractions(tender_id);
"""


SCHEMA_VERIFY = """
CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id INTEGER NOT NULL,
    stage TEXT NOT NULL,
    status TEXT,
    issues_json TEXT,
    confidence REAL,
    retries INTEGER DEFAULT 0,
    needs_review INTEGER DEFAULT 0,
    model TEXT,
    tokens INTEGER DEFAULT 0,
    cost REAL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verifications_tender ON verifications(tender_id);
"""


SCHEMA_SUPPLIERS = """
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tender_id INTEGER NOT NULL,
    items_json TEXT,
    total_cost REAL,
    tender_value REAL,
    currency TEXT,
    margin REAL,
    matched_count INTEGER DEFAULT 0,
    unmatched_count INTEGER DEFAULT 0,
    margin_partial INTEGER DEFAULT 0,
    model TEXT,
    tokens INTEGER DEFAULT 0,
    cost REAL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_suppliers_tender ON suppliers(tender_id);
"""


def _column_exists(conn, table, column):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any((r["name"] if hasattr(r, "keys") else r[1]) == column for r in rows)


def _migrate(conn):
    if not _column_exists(conn, "suppliers", "margin_partial"):
        conn.execute("ALTER TABLE suppliers ADD COLUMN margin_partial INTEGER DEFAULT 0")
        conn.commit()
    if _column_exists(conn, "crawl_state", "site_id") and \
            not _column_exists(conn, "crawl_state", "total_estimate"):
        conn.execute("ALTER TABLE crawl_state ADD COLUMN total_estimate INTEGER")
        conn.commit()
    if _column_exists(conn, "crawl_state", "site_id") and \
            not _column_exists(conn, "crawl_state", "note"):
        conn.execute("ALTER TABLE crawl_state ADD COLUMN note TEXT")
        conn.commit()
    if _column_exists(conn, "crawl_state", "site_id") and \
            not _column_exists(conn, "crawl_state", "detected_count"):
        conn.execute("ALTER TABLE crawl_state ADD COLUMN detected_count INTEGER")
    if _column_exists(conn, "crawl_state", "site_id") and \
            not _column_exists(conn, "crawl_state", "page_hash"):
        conn.execute("ALTER TABLE crawl_state ADD COLUMN page_hash TEXT")
        conn.commit()
    if not _column_exists(conn, "tenders", "origin"):
        conn.execute("ALTER TABLE tenders ADD COLUMN origin TEXT")
        conn.commit()
    if not _column_exists(conn, "tenders", "dedup_key"):
        conn.execute("ALTER TABLE tenders ADD COLUMN dedup_key TEXT")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tenders_dedup ON tenders(dedup_key)")
        conn.commit()
    conn.execute("CREATE TABLE IF NOT EXISTS recheck_state("
                 "tender_id INTEGER PRIMARY KEY, content_hash TEXT, checked_at INTEGER)")
    conn.commit()
    if not _column_exists(conn, "accounts", "role"):
        conn.execute("ALTER TABLE accounts ADD COLUMN role TEXT")
        conn.execute("UPDATE accounts SET role='admin' WHERE role IS NULL")
        conn.commit()


SCHEMA_SUPERVISOR = """
CREATE TABLE IF NOT EXISTS supervisor_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    digest_json TEXT,
    escalations_json TEXT,
    coverage_json TEXT,
    autonomy TEXT,
    escalations_done INTEGER DEFAULT 0,
    human_needed INTEGER DEFAULT 0,
    cost REAL DEFAULT 0,
    created_at REAL NOT NULL
);
"""
