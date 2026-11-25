from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "documents").mkdir(exist_ok=True)
        self.path = self.root / "library.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, filename TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, page_count INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pages (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    page_index INTEGER NOT NULL, width REAL NOT NULL, height REAL NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0, UNIQUE(task_id, page_index)
                );
                CREATE TABLE IF NOT EXISTS boxes (
                    id TEXT PRIMARY KEY, page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                    position INTEGER NOT NULL, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                    status TEXT NOT NULL, total INTEGER NOT NULL, done INTEGER NOT NULL DEFAULT 0,
                    errors INTEGER NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS boxes_page ON boxes(page_id);
                CREATE INDEX IF NOT EXISTS jobs_task ON jobs(task_id, created_at);
                CREATE TABLE IF NOT EXISTS job_pages (
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
                    PRIMARY KEY(job_id, page_id)
                );
                CREATE INDEX IF NOT EXISTS job_pages_page ON job_pages(page_id);
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(pages)")}
            if "image_file" not in columns:
                db.execute("ALTER TABLE pages ADD COLUMN image_file TEXT NOT NULL DEFAULT ''")
            if "confirmed_revision" not in columns:
                db.execute("ALTER TABLE pages ADD COLUMN confirmed_revision INTEGER NOT NULL DEFAULT -1")
            if "no_parts_reason" not in columns:
                db.execute("ALTER TABLE pages ADD COLUMN no_parts_reason TEXT NOT NULL DEFAULT ''")
            db.execute("""CREATE TABLE IF NOT EXISTS share_receipts (
                task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
                submission_id INTEGER NOT NULL, user_id INTEGER NOT NULL, data TEXT NOT NULL
            )""")
            db.execute("PRAGMA user_version=4")
            db.execute(
                "UPDATE jobs SET status='interrupted', message='应用已关闭，可继续识别未完成项。' "
                "WHERE status IN ('queued','running','cancelling')"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def one(self, sql, args=()):
        with self.connect() as db:
            row = db.execute(sql, args).fetchone()
            return dict(row) if row else None

    def all(self, sql, args=()):
        with self.connect() as db:
            return [dict(row) for row in db.execute(sql, args)]

    def boxes(self, page_id):
        return [
            json.loads(row["data"])
            for row in self.all("SELECT data FROM boxes WHERE page_id=? ORDER BY position", (page_id,))
        ]
