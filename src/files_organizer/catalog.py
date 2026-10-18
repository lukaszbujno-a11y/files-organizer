from __future__ import annotations

import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

from .config import Config
from .exif_reader import IMAGE_SUFFIXES, exif_string, exif_taken_at, iter_media_files, read_metadata_batch
from .metadata import COUNTRY_TAG_PREFIX, LOCATION_TAG_PREFIX, PERSON_TAG_PREFIX
from .models import Photo, RecognizedLocation

LogFn = Callable[[str], None]

DEFAULT_CATALOG_PATH = Path("~/.cache/files-organizer/catalog.sqlite")

# Bump whenever _SCHEMA changes. The catalog only mirrors what's in the files themselves (plus
# location names that can be looked up again), so an outdated one is simply rebuilt from scratch.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,      -- absolute
    size INTEGER NOT NULL,          -- size + mtime_ns tell whether the file changed since its scan
    mtime_ns INTEGER NOT NULL,
    media_type TEXT NOT NULL,       -- image | video
    taken_at TEXT,                  -- ISO 8601, local time as written in EXIF
    date_source TEXT NOT NULL,      -- exif | mtime (no date in EXIF, file modification time used)
    make TEXT,
    model TEXT,
    gps_lat REAL,
    gps_lon REAL,
    city TEXT,                      -- filled in by the `location` rule once it resolves the GPS
    country TEXT,
    location_source TEXT,           -- "<backend>:<language>" the names above came from
    scanned_at TEXT NOT NULL
);
CREATE INDEX files_taken_at ON files(taken_at);
CREATE INDEX files_model ON files(model);

CREATE TABLE tags (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,             -- person | location | country | keyword
    value TEXT NOT NULL,
    PRIMARY KEY (file_id, kind, value)
);
CREATE INDEX tags_kind_value ON tags(kind, value);

CREATE TABLE scans (
    id INTEGER PRIMARY KEY,
    root TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,               -- NULL when the scan was stopped
    added INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    removed INTEGER NOT NULL DEFAULT 0,
    unchanged INTEGER NOT NULL DEFAULT 0
);
"""

_TAG_KINDS = ((PERSON_TAG_PREFIX, "person"), (LOCATION_TAG_PREFIX, "location"), (COUNTRY_TAG_PREFIX, "country"))

_FILE_COLUMNS = (
    "path, size, mtime_ns, media_type, taken_at, date_source, make, model, gps_lat, gps_lon, scanned_at"
)


@dataclass(frozen=True)
class CatalogEntry:
    path: Path
    size: int
    mtime_ns: int
    media_type: str
    taken_at: datetime | None
    date_source: str
    make: str | None = None
    model: str | None = None
    gps: tuple[float, float] | None = None
    city: str | None = None
    country: str | None = None
    location_source: str | None = None
    tags: tuple[tuple[str, str], ...] = ()

    def to_photo(self, path: Path | None = None) -> Photo:
        """The pipeline's view of this file; `path` keeps the caller's spelling of it (e.g. relative)."""
        return Photo(path=path or self.path, taken_at=self.taken_at, camera_model=self.model)

    def tag_values(self, kind: str) -> list[str]:
        return [value for tag_kind, value in self.tags if tag_kind == kind]


@dataclass(frozen=True)
class ScanResult:
    paths: list[Path]  # every media file found under the root, as `iter_media_files` yields them
    added: int = 0
    updated: int = 0
    removed: int = 0
    unchanged: int = 0
    stopped: bool = False

    def describe(self) -> str:
        return f"nowe: {self.added}, zmienione: {self.updated}, usunięte: {self.removed}, bez zmian: {self.unchanged}"


@dataclass(frozen=True)
class CatalogQuery:
    taken_from: date | None = None
    taken_to: date | None = None  # inclusive
    model: str | None = None
    country: str | None = None  # matches the `location` rule's result or a Country: tag
    person: str | None = None
    without_exif_date: bool = False
    without_gps: bool = False
    limit: int | None = 1000


class Catalog:
    """Local SQLite database of the media files seen so far and their metadata.

    `scan` walks a directory and runs exiftool only on files that are new or changed since the
    last scan (judged by size + modification time), in batches of one exiftool process each.
    Everything else - the pipeline's per-file metadata, the location rule's GPS and resolved
    place names, searching - is then answered from the database.

    A connection can only be used from the thread that opened it (sqlite3's default), so open
    a Catalog inside the worker thread that uses it.
    """

    def __init__(self, path: str | Path = DEFAULT_CATALOG_PATH):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, timeout=10)
        self._db.row_factory = sqlite3.Row
        # WAL lets the watchers / GUI read while a scan is writing
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> Catalog:
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version == SCHEMA_VERSION:
            return
        with self._db:
            for table in ("tags", "scans", "files"):
                self._db.execute(f"DROP TABLE IF EXISTS {table}")
            self._db.executescript(_SCHEMA)
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    # --- scanning -------------------------------------------------------------------------

    def scan(
        self,
        root: Path,
        log: LogFn | None = None,
        should_stop: Callable[[], bool] | None = None,
        batch_size: int = 200,
    ) -> ScanResult:
        """Bring the catalog up to date with the media files under `root`.

        Unchanged files cost one `stat` each; new and changed ones are read with exiftool,
        `batch_size` files per process, committing after each batch so a stopped scan keeps what
        it already read. Files that are in the catalog under `root` but no longer on disk are
        removed - but only once the whole directory was walked, so a stopped walk never drops
        anything.
        """
        log = log or (lambda message: None)
        stopped = lambda: should_stop is not None and should_stop()
        started = time.monotonic()
        scan_id = self._start_scan(root)

        paths: list[Path] = []
        on_disk: dict[str, tuple[Path, int, int]] = {}
        for path in iter_media_files(root):
            if stopped():
                return ScanResult(paths=paths, stopped=True)
            stat = path.stat()
            paths.append(path)
            on_disk[_key(path)] = (path, stat.st_size, stat.st_mtime_ns)

        known = {
            row["path"]: (row["size"], row["mtime_ns"])
            for row in self._db.execute(
                "SELECT path, size, mtime_ns FROM files WHERE path >= ? AND path < ?", _prefix_range(root)
            )
        }
        to_read = [key for key, (_, size, mtime_ns) in on_disk.items() if known.get(key) != (size, mtime_ns)]
        added = sum(1 for key in to_read if key not in known)
        missing = [key for key in known if key not in on_disk]
        with self._db:
            self._db.executemany("DELETE FROM files WHERE path = ?", [(key,) for key in missing])
        log(f"  katalog: {len(on_disk)} plików, do odczytu {len(to_read)} (nowe: {added}), usunięte z dysku: {len(missing)}")

        done = 0
        for start in range(0, len(to_read), batch_size):
            if stopped():
                self._finish_scan(scan_id, added, len(to_read) - added, len(missing), len(on_disk) - len(to_read), done=False)
                return ScanResult(paths=paths, stopped=True)
            batch = [on_disk[key][0] for key in to_read[start : start + batch_size]]
            self._store(batch, read_metadata_batch(batch))
            done += len(batch)
            log(f"  katalog: odczytano {done}/{len(to_read)} ({_elapsed(started)})")

        result = ScanResult(
            paths=paths, added=added, updated=len(to_read) - added, removed=len(missing), unchanged=len(on_disk) - len(to_read)
        )
        self._finish_scan(scan_id, result.added, result.updated, result.removed, result.unchanged, done=True)
        return result

    def refresh(self, path: Path) -> CatalogEntry | None:
        """Read `path` with exiftool right now and store it - for a file `get` had no fresh entry for.
        None only when the file no longer exists."""
        self._store([path], read_metadata_batch([path]))
        return self._entry(_key(path))

    def _store(self, paths: list[Path], metadata: dict[Path, dict]) -> None:
        # exiftool reports files under the spelling they were given in, so look them up that way
        scanned_at = datetime.now().isoformat(timespec="seconds")
        with self._db:
            for path in paths:
                try:
                    stat = path.stat()
                except FileNotFoundError:  # deleted since the directory was walked
                    continue
                data = metadata.get(path, {})
                taken_at = exif_taken_at(data)
                date_source = "exif" if taken_at is not None else "mtime"
                if taken_at is None:
                    taken_at = datetime.fromtimestamp(stat.st_mtime)
                gps = _gps(data)
                file_id = self._db.execute(
                    f"""INSERT INTO files ({_FILE_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        size = excluded.size, mtime_ns = excluded.mtime_ns, media_type = excluded.media_type,
                        taken_at = excluded.taken_at, date_source = excluded.date_source,
                        make = excluded.make, model = excluded.model,
                        gps_lat = excluded.gps_lat, gps_lon = excluded.gps_lon, scanned_at = excluded.scanned_at,
                        city = NULL, country = NULL, location_source = NULL
                    RETURNING id""",
                    (
                        _key(path),
                        stat.st_size,
                        stat.st_mtime_ns,
                        "image" if path.suffix.lower() in IMAGE_SUFFIXES else "video",
                        taken_at.isoformat(),
                        date_source,
                        exif_string(data.get("Make")),
                        exif_string(data.get("Model")),
                        gps[0] if gps else None,
                        gps[1] if gps else None,
                        scanned_at,
                    ),
                ).fetchone()[0]
                self._db.execute("DELETE FROM tags WHERE file_id = ?", (file_id,))
                self._db.executemany(
                    "INSERT OR IGNORE INTO tags (file_id, kind, value) VALUES (?, ?, ?)",
                    [(file_id, kind, value) for kind, value in _parse_keywords(data.get("Keywords"))],
                )

    def _start_scan(self, root: Path) -> int:
        with self._db:
            return self._db.execute(
                "INSERT INTO scans (root, started_at) VALUES (?, ?)", (_key(root), datetime.now().isoformat(timespec="seconds"))
            ).lastrowid

    def _finish_scan(self, scan_id: int, added: int, updated: int, removed: int, unchanged: int, done: bool) -> None:
        with self._db:
            self._db.execute(
                "UPDATE scans SET finished_at = ?, added = ?, updated = ?, removed = ?, unchanged = ? WHERE id = ?",
                (datetime.now().isoformat(timespec="seconds") if done else None, added, updated, removed, unchanged, scan_id),
            )

    # --- reading --------------------------------------------------------------------------

    def get(self, path: Path) -> CatalogEntry | None:
        """The catalog's entry for `path`, or None when it has none or the file changed since."""
        entry = self._entry(_key(path))
        if entry is None:
            return None
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        if (stat.st_size, stat.st_mtime_ns) != (entry.size, entry.mtime_ns):
            return None
        return entry

    def _entry(self, key: str) -> CatalogEntry | None:
        row = self._db.execute("SELECT * FROM files WHERE path = ?", (key,)).fetchone()
        if row is None:
            return None
        return self._entries([row])[0]

    def _entries(self, rows: list[sqlite3.Row]) -> list[CatalogEntry]:
        tags: dict[int, list[tuple[str, str]]] = {row["id"]: [] for row in rows}
        ids = list(tags)
        # chunked to stay under SQLite's limit on bound parameters
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            for tag in self._db.execute(
                f"SELECT file_id, kind, value FROM tags WHERE file_id IN ({','.join('?' * len(chunk))}) ORDER BY kind, value",
                chunk,
            ):
                tags[tag["file_id"]].append((tag["kind"], tag["value"]))
        return [
            CatalogEntry(
                path=Path(row["path"]),
                size=row["size"],
                mtime_ns=row["mtime_ns"],
                media_type=row["media_type"],
                taken_at=datetime.fromisoformat(row["taken_at"]) if row["taken_at"] else None,
                date_source=row["date_source"],
                make=row["make"],
                model=row["model"],
                gps=(row["gps_lat"], row["gps_lon"]) if row["gps_lat"] is not None else None,
                city=row["city"],
                country=row["country"],
                location_source=row["location_source"],
                tags=tuple(tags[row["id"]]),
            )
            for row in rows
        ]

    # --- updates from the pipeline -------------------------------------------------------

    def set_location(self, path: Path, location: RecognizedLocation, source: str) -> None:
        """Remember the place the `location` rule resolved `path`'s GPS to (`source` = backend:language)."""
        with self._db:
            self._db.execute(
                "UPDATE files SET city = ?, country = ?, location_source = ? WHERE path = ?",
                (location.city, location.country, source, _key(path)),
            )

    def record_placed(self, source: Path, destination: Path, moved: bool) -> None:
        """Follow a file the pipeline copied/moved to `destination`: a move renames its entry, a copy
        gets an entry of its own - so the organized library is searchable without scanning it."""
        source_key, destination_key = _key(source), _key(destination)
        if source_key == destination_key:
            return
        stat = destination.stat()
        with self._db:
            self._db.execute("DELETE FROM files WHERE path = ?", (destination_key,))
            if moved:
                self._db.execute(
                    "UPDATE files SET path = ?, size = ?, mtime_ns = ? WHERE path = ?",
                    (destination_key, stat.st_size, stat.st_mtime_ns, source_key),
                )
                return
            row = self._db.execute(
                f"""INSERT INTO files ({_FILE_COLUMNS}, city, country, location_source)
                SELECT ?, ?, ?, media_type, taken_at, date_source, make, model, gps_lat, gps_lon, scanned_at,
                       city, country, location_source
                FROM files WHERE path = ? RETURNING id""",
                (destination_key, stat.st_size, stat.st_mtime_ns, source_key),
            ).fetchone()
            if row is not None:
                self._db.execute(
                    "INSERT INTO tags (file_id, kind, value) SELECT ?, kind, value FROM tags "
                    "WHERE file_id = (SELECT id FROM files WHERE path = ?)",
                    (row[0], source_key),
                )

    # --- searching ------------------------------------------------------------------------

    def search(self, query: CatalogQuery) -> list[CatalogEntry]:
        where, params = _where(query)
        sql = f"SELECT * FROM files {where} ORDER BY taken_at, path"
        if query.limit is not None:
            sql += f" LIMIT {int(query.limit)}"
        return self._entries(self._db.execute(sql, params).fetchall())

    def count(self, query: CatalogQuery) -> int:
        where, params = _where(query)
        return self._db.execute(f"SELECT count(*) FROM files {where}", params).fetchone()[0]

    def facets(self) -> dict[str, list[str]]:
        """Values to offer in search filters: phone models, countries and people seen so far."""
        models = [row[0] for row in self._db.execute("SELECT DISTINCT model FROM files WHERE model IS NOT NULL ORDER BY model")]
        countries = [
            row[0]
            for row in self._db.execute(
                "SELECT country FROM files WHERE country IS NOT NULL "
                "UNION SELECT value FROM tags WHERE kind = 'country' ORDER BY 1"
            )
        ]
        people = [row[0] for row in self._db.execute("SELECT DISTINCT value FROM tags WHERE kind = 'person' ORDER BY value")]
        return {"models": models, "countries": countries, "people": people}


def open_catalog(config: Config) -> Catalog | None:
    """The catalog configured in `config.catalog` (on by default), or None when it's disabled."""
    section = config.catalog or {}
    if not section.get("enabled", True):
        return None
    return Catalog(section.get("path") or DEFAULT_CATALOG_PATH)


def _where(query: CatalogQuery) -> tuple[str, list]:
    clauses, params = [], []
    if query.taken_from is not None:
        clauses.append("taken_at >= ?")
        params.append(query.taken_from.isoformat())
    if query.taken_to is not None:
        clauses.append("taken_at < ?")
        params.append((query.taken_to + timedelta(days=1)).isoformat())
    if query.model:
        clauses.append("model = ?")
        params.append(query.model)
    if query.country:
        clauses.append(
            "(country = ? COLLATE NOCASE OR EXISTS "
            "(SELECT 1 FROM tags WHERE file_id = files.id AND kind = 'country' AND value = ? COLLATE NOCASE))"
        )
        params += [query.country, query.country]
    if query.person:
        clauses.append("EXISTS (SELECT 1 FROM tags WHERE file_id = files.id AND kind = 'person' AND value = ? COLLATE NOCASE)")
        params.append(query.person)
    if query.without_exif_date:
        clauses.append("date_source = 'mtime'")
    if query.without_gps:
        clauses.append("gps_lat IS NULL")
    return ("WHERE " + " AND ".join(clauses) if clauses else ""), params


def _key(path: Path) -> str:
    # absolute but not resolved: /tmp vs /private/tmp style symlinks keep the spelling they were scanned with
    return os.path.abspath(path)


def _prefix_range(root: Path) -> tuple[str, str]:
    """`(low, high)` such that `low <= path < high` selects exactly the paths inside `root` -
    an index-friendly replacement for `LIKE 'root/%'` (which would also treat `_` as a wildcard)."""
    prefix = _key(root)
    if not prefix.endswith(os.sep):
        prefix += os.sep
    return prefix, prefix[:-1] + chr(ord(os.sep) + 1)


def _gps(data: dict) -> tuple[float, float] | None:
    latitude, longitude = data.get("GPSLatitude"), data.get("GPSLongitude")
    try:
        return (float(latitude), float(longitude)) if latitude is not None and longitude is not None else None
    except (TypeError, ValueError):
        return None


def _parse_keywords(keywords) -> list[tuple[str, str]]:
    if keywords is None:
        return []
    values = keywords if isinstance(keywords, list) else [keywords]
    return [_parse_keyword(str(value)) for value in values]


def _parse_keyword(value: str) -> tuple[str, str]:
    for prefix, kind in _TAG_KINDS:
        if value.startswith(prefix):
            return kind, value[len(prefix) :]
    return "keyword", value


def _elapsed(since: float) -> str:
    return f"{time.monotonic() - since:.1f} s"
