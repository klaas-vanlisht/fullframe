"""SQLite storage. One shared connection guarded by a lock (the app is small)."""
import os
import sqlite3
import threading

from .util import DATA_DIR

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    url TEXT UNIQUE,
    source_id TEXT,
    title TEXT,
    description TEXT,
    image TEXT,
    published TEXT,
    fetched TEXT,
    story_id INTEGER,
    body TEXT
);
CREATE INDEX IF NOT EXISTS idx_articles_story ON articles(story_id);
CREATE INDEX IF NOT EXISTS idx_articles_pub ON articles(published);
CREATE INDEX IF NOT EXISTS idx_articles_src_title ON articles(source_id, title);

CREATE TABLE IF NOT EXISTS stories (
    id INTEGER PRIMARY KEY,
    first_seen TEXT,
    last_article_at TEXT,
    headline TEXT,
    image TEXT,
    topic TEXT,
    ai TEXT,
    ai_at TEXT,
    ai_n_sources INTEGER DEFAULT 0,
    ai_error TEXT,
    coherent INTEGER DEFAULT 1,
    lang_checked INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_stories_last ON stories(last_article_at);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS source_status (
    id TEXT PRIMARY KEY,
    status TEXT,
    via TEXT,
    last_fetch TEXT,
    last_count INTEGER,
    error TEXT
);
"""


class DB:
    def __init__(self, path=None):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.path = path or os.path.join(DATA_DIR, "news.db")
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(stories)")}
            if "lang_checked" not in cols:  # upgrade older databases
                self.conn.execute("ALTER TABLE stories ADD COLUMN lang_checked INTEGER DEFAULT 0")
            self.conn.commit()

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        with self.lock:
            r = self.conn.execute(sql, args).fetchone()
            return dict(r) if r else None

    def x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def close(self):
        with self.lock:
            self.conn.commit()
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.close()

    def many(self, sql, rows):
        with self.lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()
