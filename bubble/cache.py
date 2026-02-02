"""File-level caching for extraction results."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import msgpack  # type: ignore[import-untyped]

from bubble import __version__
from bubble.models import (
    CallSite,
    CatchSite,
    ClassDef,
    Entrypoint,
    FunctionDef,
    GlobalHandler,
    ImportInfo,
    RaiseSite,
)

if TYPE_CHECKING:
    from bubble.extractor import FileExtraction

CACHE_VERSION = "3"
CACHE_FILENAME = "cache.sqlite"


class FileCache:
    """SQLite-backed cache for file extraction results."""

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = cache_dir / CACHE_FILENAME
        self.db = self._open_db()

    def _open_db(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db_path, check_same_thread=False)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")

        db.executescript("""
            CREATE TABLE IF NOT EXISTS cache_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS file_cache (
                file_path TEXT PRIMARY KEY,
                mtime_ns INTEGER,
                size INTEGER,
                content_hash TEXT,
                extraction BLOB
            );
            CREATE INDEX IF NOT EXISTS idx_file_cache_mtime ON file_cache(mtime_ns);
        """)

        if not self._validate_version(db):
            self._clear(db)
            self._set_version(db)

        return db

    def _validate_version(self, db: sqlite3.Connection) -> bool:
        row = db.execute("SELECT value FROM cache_meta WHERE key = 'version'").fetchone()
        if row is None or row[0] != CACHE_VERSION:
            return False

        row = db.execute("SELECT value FROM cache_meta WHERE key = 'flow_version'").fetchone()
        if row is None or row[0] != __version__:
            return False

        return True

    def _set_version(self, db: sqlite3.Connection) -> None:
        db.execute(
            "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('version', ?)",
            (CACHE_VERSION,),
        )
        db.execute(
            "INSERT OR REPLACE INTO cache_meta (key, value) VALUES ('flow_version', ?)",
            (__version__,),
        )
        db.commit()

    def _clear(self, db: sqlite3.Connection) -> None:
        db.execute("DELETE FROM file_cache")
        db.execute("DELETE FROM cache_meta")
        db.commit()

    def get(self, file_path: Path) -> FileExtraction | None:
        """Get cached extraction if still valid."""
        try:
            stat = file_path.stat()
        except OSError:
            return None

        row = self.db.execute(
            "SELECT mtime_ns, size, extraction FROM file_cache WHERE file_path = ?",
            (str(file_path),),
        ).fetchone()

        if row is None:
            return None

        cached_mtime, cached_size, extraction_blob = row
        if stat.st_mtime_ns != cached_mtime or stat.st_size != cached_size:
            return None

        return self._deserialize(extraction_blob)

    def put(self, file_path: Path, extraction: FileExtraction) -> None:
        """Cache an extraction result."""
        try:
            stat = file_path.stat()
            content_hash = hashlib.sha256(file_path.read_bytes()).hexdigest()
        except OSError:
            return

        self.db.execute(
            """INSERT OR REPLACE INTO file_cache
               (file_path, mtime_ns, size, content_hash, extraction)
               VALUES (?, ?, ?, ?, ?)""",
            (
                str(file_path),
                stat.st_mtime_ns,
                stat.st_size,
                content_hash,
                self._serialize(extraction),
            ),
        )
        self.db.commit()

    def _serialize(self, extraction: FileExtraction) -> bytes:
        def class_to_dict(c: ClassDef) -> dict[str, Any]:
            d = asdict(c)
            d["abstract_methods"] = list(c.abstract_methods)
            return d

        data = {
            "functions": [asdict(f) for f in extraction.functions],
            "classes": [class_to_dict(c) for c in extraction.classes],
            "raise_sites": [asdict(r) for r in extraction.raise_sites],
            "catch_sites": [asdict(c) for c in extraction.catch_sites],
            "call_sites": [asdict(c) for c in extraction.call_sites],
            "imports": [asdict(i) for i in extraction.imports],
            "entrypoints": [asdict(e) for e in extraction.entrypoints],
            "global_handlers": [asdict(g) for g in extraction.global_handlers],
            "import_map": extraction.import_map,
            "return_types": extraction.return_types,
            "detected_frameworks": list(extraction.detected_frameworks),
        }
        return msgpack.packb(data)  # type: ignore[no-any-return]

    def _deserialize(self, blob: bytes) -> FileExtraction:
        """Deserialize msgpack blob to FileExtraction. Types from msgpack are dynamic."""
        from bubble.extractor import FileExtraction as FE

        raw: Any = msgpack.unpackb(blob)
        data: dict[str, list[dict[str, Any]] | dict[str, str]] = raw
        result = FE()

        funcs: list[dict[str, Any]] = data["functions"]  # type: ignore[assignment]
        result.functions = [FunctionDef(**f) for f in funcs]

        classes: list[dict[str, Any]] = data["classes"]  # type: ignore[assignment]
        for c in classes:
            if "abstract_methods" in c:
                c["abstract_methods"] = set(c["abstract_methods"])
        result.classes = [ClassDef(**c) for c in classes]

        raises: list[dict[str, Any]] = data["raise_sites"]  # type: ignore[assignment]
        result.raise_sites = [RaiseSite(**r) for r in raises]

        catches: list[dict[str, Any]] = data["catch_sites"]  # type: ignore[assignment]
        result.catch_sites = [CatchSite(**c) for c in catches]

        calls: list[dict[str, Any]] = data["call_sites"]  # type: ignore[assignment]
        result.call_sites = [CallSite(**c) for c in calls]

        imports: list[dict[str, Any]] = data["imports"]  # type: ignore[assignment]
        result.imports = [ImportInfo(**i) for i in imports]

        eps: list[dict[str, Any]] = data["entrypoints"]  # type: ignore[assignment]
        result.entrypoints = [Entrypoint(**e) for e in eps]

        handlers: list[dict[str, Any]] = data["global_handlers"]  # type: ignore[assignment]
        result.global_handlers = [GlobalHandler(**g) for g in handlers]

        result.import_map = data["import_map"]  # type: ignore[assignment]
        result.return_types = data["return_types"]  # type: ignore[assignment]
        result.detected_frameworks = set(data.get("detected_frameworks", []))  # type: ignore[arg-type]

        return result

    def stats(self) -> dict[str, int]:
        """Return cache statistics."""
        count = self.db.execute("SELECT COUNT(*) FROM file_cache").fetchone()[0]
        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        return {"file_count": count, "size_bytes": size}

    def close(self) -> None:
        """Close the database connection."""
        self.db.close()
