from __future__ import annotations


DDL = (
    """
    CREATE TABLE IF NOT EXISTS partner_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        partner TEXT NOT NULL,
        filename TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        received_at REAL NOT NULL,
        sheets_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'ingested',
        report_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_partner_files_hash ON partner_files(partner, sha256)",
    """
    CREATE TABLE IF NOT EXISTS partner_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id INTEGER NOT NULL,
        partner TEXT NOT NULL,
        sheet TEXT NOT NULL,
        row_no INTEGER NOT NULL,
        brand TEXT,
        mpn TEXT,
        mpn_norm TEXT,
        description TEXT,
        category_path TEXT,
        price_original REAL,
        currency TEXT,
        price_usd REAL,
        promo_usd REAL,
        warranty TEXT,
        stock TEXT,
        extra_json TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_partner_offers_mpn ON partner_offers(mpn_norm)",
    "CREATE INDEX IF NOT EXISTS ix_partner_offers_partner ON partner_offers(partner)",
    "CREATE INDEX IF NOT EXISTS ix_partner_offers_price ON partner_offers(price_usd)",
    "CREATE INDEX IF NOT EXISTS ix_partner_offers_file ON partner_offers(file_id)",
    """
    CREATE TABLE IF NOT EXISTS partner_profiles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        partner TEXT NOT NULL UNIQUE,
        profile_json TEXT NOT NULL,
        updated_at REAL NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS partner_staging (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        partner TEXT NOT NULL,
        filename TEXT NOT NULL,
        path TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        detected_json TEXT NOT NULL DEFAULT '{}',
        created_at REAL NOT NULL
    )
    """,
)


def _add_column_if_missing(conn, table, column, decl):
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")


def init_partner_schema(conn):
    for stmt in DDL:
        conn.execute(stmt)
    _add_column_if_missing(conn, "partner_offers", "product_type", "TEXT")
    _add_column_if_missing(conn, "partner_offers", "type_source", "TEXT")
    _add_column_if_missing(conn, "partner_offers", "active", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "partner_files", "upload_path", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_partner_offers_type "
                 "ON partner_offers(product_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_partner_offers_active "
                 "ON partner_offers(active)")
    conn.commit()
