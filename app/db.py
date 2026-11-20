import json
import sqlite3
import threading
import time

from .config import DB_PATH

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row

with _lock:
    _conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            platform TEXT NOT NULL,
            added_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER NOT NULL,
            channel_name TEXT NOT NULL,
            peak_time REAL NOT NULL,
            created_at REAL NOT NULL,
            score REAL NOT NULL,
            reasons TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pendente',
            file_h TEXT,
            file_v TEXT,
            thumb TEXT,
            transcript TEXT
        );
        CREATE TABLE IF NOT EXISTS vods (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            name TEXT NOT NULL,
            platform TEXT NOT NULL,
            title TEXT,
            status TEXT NOT NULL DEFAULT 'na fila',
            progress REAL NOT NULL DEFAULT 0,
            error TEXT,
            added_at REAL NOT NULL
        );
        """
    )
    # colunas novas (bancos de versões antigas ganham elas sozinhos)
    NEW = {
        "channels": {"cam": "TEXT"},
        "clips": {"platform": "TEXT", "url": "TEXT", "cam": "TEXT", "cat": "TEXT", "subject": "TEXT",
                  "title": "TEXT", "title_idx": "INTEGER DEFAULT 0", "descr": "TEXT", "tags": "TEXT",
                  "chat_top": "TEXT", "overlay": "TEXT", "warn": "TEXT", "rendering": "INTEGER DEFAULT 0",
                  "source": "TEXT DEFAULT 'live'", "vod_id": "INTEGER",
                  "layout": "TEXT DEFAULT 'auto'", "layout_used": "TEXT", "yt_tags": "TEXT",
                  "overlay_on": "INTEGER DEFAULT 1", "overlay_applied": "TEXT"},
    }
    for table, cols in NEW.items():
        have = {r[1] for r in _conn.execute(f"PRAGMA table_info({table})")}
        for col, typ in cols.items():
            if col not in have:
                _conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    _conn.commit()


def _row(r):
    d = dict(r)
    if d.get("cam"):
        try:
            d["cam"] = json.loads(d["cam"])
        except Exception:
            d["cam"] = None
    return d


def query(sql, params=()):
    with _lock:
        return [_row(r) for r in _conn.execute(sql, params).fetchall()]


def execute(sql, params=()):
    with _lock:
        cur = _conn.execute(sql, params)
        _conn.commit()
        return cur.lastrowid


def insert(table, data: dict):
    data = {k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in data.items()}
    cols = ", ".join(data)
    marks = ", ".join("?" for _ in data)
    return execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(data.values()))


def update(table, row_id, data: dict):
    data = {k: (json.dumps(v) if isinstance(v, dict) else v) for k, v in data.items()}
    sets = ", ".join(f"{k}=?" for k in data)
    execute(f"UPDATE {table} SET {sets} WHERE id=?", (*data.values(), row_id))


def add_channel(url, name, platform):
    return insert("channels", {"url": url, "name": name, "platform": platform, "added_at": time.time()})
