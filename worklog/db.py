"""worklog 数据库层：schema 与连接。零第三方依赖，仅 sqlite3。"""

from __future__ import annotations

import json
import pathlib
import sqlite3

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "projects.json"
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "worklog.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    path        TEXT,
    color       TEXT,
    kind        TEXT,
    sensitive   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS event (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    source_ref  TEXT NOT NULL,
    ts          INTEGER NOT NULL,
    day         TEXT NOT NULL,
    session_id  TEXT,
    project_id  TEXT,
    kind        TEXT NOT NULL,
    signal      TEXT,
    raw_ref     TEXT,
    UNIQUE (source, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_event_day ON event(day);
CREATE INDEX IF NOT EXISTS idx_event_session ON event(session_id);

CREATE TABLE IF NOT EXISTS work_unit (
    id               TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    project_id       TEXT NOT NULL,
    kind             TEXT NOT NULL,
    start_day        TEXT,
    end_day          TEXT,
    span_days        INTEGER NOT NULL DEFAULT 0,
    active_day_count INTEGER NOT NULL DEFAULT 0,
    max_streak       INTEGER NOT NULL DEFAULT 0,
    active_days      TEXT,
    file_count       INTEGER NOT NULL DEFAULT 0,
    additions        INTEGER NOT NULL DEFAULT 0,
    deletions        INTEGER NOT NULL DEFAULT 0,
    is_noise         INTEGER NOT NULL DEFAULT 0,
    masked           INTEGER NOT NULL DEFAULT 0,
    raw_title        TEXT
);

CREATE INDEX IF NOT EXISTS idx_wu_start ON work_unit(start_day);

CREATE TABLE IF NOT EXISTS artifact (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    work_unit_id TEXT NOT NULL,
    path         TEXT NOT NULL,
    action       TEXT,
    additions    INTEGER DEFAULT 0,
    deletions    INTEGER DEFAULT 0,
    ts           INTEGER,
    day          TEXT
);

CREATE INDEX IF NOT EXISTS idx_art_wu ON artifact(work_unit_id);

CREATE TABLE IF NOT EXISTS session_block (
    block_id    TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    day         TEXT,
    start_ts    INTEGER,
    end_ts      INTEGER,
    files       TEXT,
    additions   INTEGER,
    deletions   INTEGER,
    batch_ids   TEXT
);

CREATE INDEX IF NOT EXISTS idx_block_session ON session_block(session_id);

CREATE TABLE IF NOT EXISTS session_split (
    session_id TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    source     TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def connect(path: pathlib.Path | None = None) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path or DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def ensure_columns(con: sqlite3.Connection) -> None:
    """给已存在的表补列（schema 演进用）。"""
    cols = {r[1] for r in con.execute("PRAGMA table_info(work_unit)")}
    for col, decl in (("summary", "TEXT"), ("detail", "TEXT"), ("group_id", "TEXT"), ("session_id", "TEXT")):
        if col not in cols:
            con.execute(f"ALTER TABLE work_unit ADD COLUMN {col} {decl}")


def set_meta(con: sqlite3.Connection, key: str, value: str) -> None:    con.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None
