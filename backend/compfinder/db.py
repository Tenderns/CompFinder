from contextlib import contextmanager
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS styles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
    cover_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    info TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS images (
    id TEXT PRIMARY KEY,
    style_id TEXT NOT NULL REFERENCES styles(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('display','recognition')),
    filename TEXT NOT NULL,
    storage_name TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    position INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('display','pending','processing','ready','failed')),
    error TEXT,
    vector BLOB,
    vector_version TEXT,
    UNIQUE(style_id,role,sha256)
);
CREATE INDEX IF NOT EXISTS image_style ON images(style_id,role,position);
CREATE INDEX IF NOT EXISTS image_state ON images(role,state);
CREATE TABLE IF NOT EXISTS imports (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'uploading',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS import_files (
    job_id TEXT NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    style_id TEXT REFERENCES styles(id) ON DELETE SET NULL,
    style_name TEXT NOT NULL,
    role TEXT,
    state TEXT NOT NULL,
    message TEXT,
    PRIMARY KEY(job_id,path)
);
CREATE TABLE IF NOT EXISTS mcp_tokens (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    -- Kept readable so the page can copy it again; secret_hash is what requests are matched on.
    secret TEXT NOT NULL,
    secret_hash TEXT NOT NULL UNIQUE,
    tools TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    last_used_at TEXT
);
"""


class Database:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "compfinder.db"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)
            # Libraries created before style info existed gain the column in place.
            if "info" not in {row["name"] for row in db.execute("PRAGMA table_info(styles)")}:
                db.execute("ALTER TABLE styles ADD COLUMN info TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
