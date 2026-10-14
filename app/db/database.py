"""SQLite schema creation mirroring Android Room AppDatabase (version 5).

Column names are kept identical to the Room-generated schema (a mix of
camelCase and snake_case) so that backup files produced by the Android app
remain binary-compatible with this desktop port.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 6

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS component_master (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    part_number TEXT NOT NULL,
    mpn TEXT,
    name TEXT,
    brand TEXT,
    package_name TEXT,
    category TEXT,
    spec_json TEXT,
    description TEXT,
    source_url TEXT,
    image_local_path TEXT,
    image_url TEXT,
    updated_at INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS index_component_master_part_number
    ON component_master (part_number);
CREATE INDEX IF NOT EXISTS index_component_master_mpn ON component_master (mpn);
CREATE INDEX IF NOT EXISTS index_component_master_brand ON component_master (brand);
CREATE INDEX IF NOT EXISTS index_component_master_package_name ON component_master (package_name);

CREATE TABLE IF NOT EXISTS storage_location (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    code TEXT NOT NULL,
    displayName TEXT,
    colorHex TEXT,
    sortMode TEXT NOT NULL DEFAULT '',
    inbound_category TEXT,
    inbound_package_name TEXT,
    inbound_profile_updated_at INTEGER NOT NULL DEFAULT 0,
    remark TEXT,
    createdAt INTEGER NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS index_storage_location_code
    ON storage_location (code);

CREATE TABLE IF NOT EXISTS inventory_item (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    component_id INTEGER NOT NULL,
    location_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    last_inbound_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    FOREIGN KEY (component_id) REFERENCES component_master(id) ON DELETE CASCADE,
    FOREIGN KEY (location_id) REFERENCES storage_location(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS index_inventory_item_component_id
    ON inventory_item (component_id);
CREATE INDEX IF NOT EXISTS index_inventory_item_location_id
    ON inventory_item (location_id);
CREATE UNIQUE INDEX IF NOT EXISTS index_inventory_item_component_id_location_id
    ON inventory_item (component_id, location_id);

CREATE TABLE IF NOT EXISTS inventory_txn (
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    component_id INTEGER NOT NULL,
    location_id INTEGER NOT NULL,
    txn_type TEXT NOT NULL,
    quantity_delta INTEGER NOT NULL,
    source_type TEXT NOT NULL,
    source_ref TEXT,
    raw_payload TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (component_id) REFERENCES component_master(id) ON DELETE CASCADE,
    FOREIGN KEY (location_id) REFERENCES storage_location(id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS index_inventory_txn_component_id
    ON inventory_txn (component_id);
CREATE INDEX IF NOT EXISTS index_inventory_txn_location_id
    ON inventory_txn (location_id);
CREATE INDEX IF NOT EXISTS index_inventory_txn_txn_type ON inventory_txn (txn_type);
CREATE INDEX IF NOT EXISTS index_inventory_txn_source_type ON inventory_txn (source_type);
"""


def open_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the ERP database and ensure schema is at v5.

    The connection is configured with ``check_same_thread=False`` so it can be
    used from Qt worker threads; callers are still expected to serialize access
    (the repository layer holds a lock around write transactions).
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current < SCHEMA_VERSION:
        if current < 6:
            _migrate_v5_to_v6(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _migrate_v5_to_v6(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(component_master)").fetchall()]
    if "image_url" not in cols:
        conn.execute("ALTER TABLE component_master ADD COLUMN image_url TEXT")


def vacuum(conn: sqlite3.Connection) -> None:
    conn.execute("VACUUM")
