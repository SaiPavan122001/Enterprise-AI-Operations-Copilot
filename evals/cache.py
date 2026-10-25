"""SQLite-backed key/value cache so LLM calls are never paid for twice.

Keys are SHA-256 hashes of everything that determines the output (model,
prompt, parameters, metric name ...). Values are JSON. Safe across threads.
"""

import hashlib
import json
import sqlite3
import threading
from typing import Any

from evals.settings import load_config, repo_path

_MISSING = object()


def make_key(*parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, path=None):
        self._path = str(path or repo_path(load_config()["paths"]["cache_db"]))
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (ns TEXT, key TEXT, value TEXT, "
            "PRIMARY KEY (ns, key))"
        )
        self._conn.commit()
        self.hits = 0
        self.misses = 0

    def get(self, ns: str, key: str, default=_MISSING):
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM cache WHERE ns=? AND key=?", (ns, key)
            ).fetchone()
        if row is None:
            self.misses += 1
            return None if default is _MISSING else default
        self.hits += 1
        return json.loads(row[0])

    def has(self, ns: str, key: str) -> bool:
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM cache WHERE ns=? AND key=?", (ns, key)
            ).fetchone() is not None

    def set(self, ns: str, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO cache (ns, key, value) VALUES (?, ?, ?)",
                (ns, key, json.dumps(value, default=str, ensure_ascii=False)),
            )
            self._conn.commit()


_cache: DiskCache | None = None


def get_cache() -> DiskCache:
    global _cache
    if _cache is None:
        _cache = DiskCache()
    return _cache
