from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .exif_reader import SUPPORTED_SUFFIXES, iter_media_files
from .location_recognizers import LocationRecognizer
from .metadata import read_tagged_locations, write_location_tags
from .models import RecognizedLocation

LogFn = Callable[[str], None]
ConfirmFn = Callable[[Path, RecognizedLocation], bool]


@dataclass
class LocationDetection:
    path: Path
    location: RecognizedLocation


def scan_for_locations(
    input_dir: Path, recognizer: LocationRecognizer, log: LogFn, limit: int | None = None
) -> list[LocationDetection]:
    """One-shot: recognize a location in every media file already sitting in `input_dir`.

    Unlike `watch_for_locations`, this doesn't watch for new files and never writes tags
    itself - it just runs recognition over the whole directory and returns every detection,
    so a batch review can happen only after the whole scan is done.

    A photo can only have one location, so - unlike face scanning, where a file already
    tagged with some people might still have others left to find - a file already carrying
    a `Location:` tag is skipped outright without even running recognition on it.

    `limit`, when given, stops the scan as soon as that many detections have been collected,
    instead of always going through the whole directory.
    """
    detections = []
    for path in iter_media_files(input_dir):
        if limit is not None and len(detections) >= limit:
            log(f"Osiągnięto limit {limit} wykryć, przerywam skanowanie")
            break
        if read_tagged_locations(path):
            log(f"{path} -> lokalizacja już otagowana, pomijam")
            continue
        log(f"Analizuję: {path}")
        try:
            location = recognizer.recognize(path)
        except Exception as exc:
            log(f"{path} -> błąd rozpoznawania lokalizacji: {exc}")
            continue
        if location is None:
            log(f"{path} -> brak danych GPS lub nie rozpoznano lokalizacji")
            continue
        log(f"{path} -> rozpoznano: {location.city}, {location.country}")
        detections.append(LocationDetection(path=path, location=location))
    return detections


class _MediaFileHandler(FileSystemEventHandler):
    def __init__(self, work_queue: "queue.Queue[Path]"):
        self.work_queue = work_queue

    def on_created(self, event) -> None:
        self._maybe_enqueue(event.is_directory, event.src_path)

    def on_moved(self, event) -> None:
        self._maybe_enqueue(event.is_directory, event.dest_path)

    def _maybe_enqueue(self, is_directory: bool, src_path: str) -> None:
        if is_directory:
            return
        path = Path(src_path)
        if path.suffix.lower() in SUPPORTED_SUFFIXES:
            self.work_queue.put(path)


def _process_one(
    path: Path, recognizer: LocationRecognizer, log: LogFn, dry_run: bool, confirm_fn: ConfirmFn | None = None
) -> None:
    if not path.exists():
        return
    if read_tagged_locations(path):
        return

    log(f"Analizuję: {path}")
    try:
        location = recognizer.recognize(path)
    except Exception as exc:
        log(f"{path} -> błąd rozpoznawania lokalizacji: {exc}")
        return

    if location is None:
        log(f"{path} -> brak danych GPS lub nie rozpoznano lokalizacji")
        return
    if dry_run:
        log(f"{path} -> (dry-run) oznaczono by tagiem: {location.city}, {location.country}")
        return
    if confirm_fn is not None and not confirm_fn(path, location):
        log(f"{path} -> pominięto na żądanie użytkownika: {location.city}, {location.country}")
        return
    write_location_tags(path, location)
    log(f"{path} -> {location.city}, {location.country}")


def _worker(
    work_queue: "queue.Queue[Path]",
    recognizer: LocationRecognizer,
    log: LogFn,
    stop_event: threading.Event,
    dry_run: bool,
    confirm_fn: ConfirmFn | None,
) -> None:
    while not stop_event.is_set():
        try:
            path = work_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _process_one(path, recognizer, log, dry_run, confirm_fn)
        finally:
            work_queue.task_done()


def watch_for_locations(
    input_dir: Path,
    recognizer: LocationRecognizer,
    log: LogFn,
    stop_event: threading.Event,
    dry_run: bool = False,
    confirm_fn: ConfirmFn | None = None,
) -> None:
    """Long-running: watch `input_dir` for new media files and tag their location on arrival.

    Independent of `run_pipeline` and of `watch_for_faces` - meant to run alongside either
    (or alone) while the user copies photos into `input_dir`. Recognition never runs inside
    the watchdog callback itself: `watchdog` only pushes paths onto a queue, and a separate
    worker thread drains it.

    `dry_run` still runs recognition but skips `write_location_tags`, logging what would have
    been tagged instead.

    `confirm_fn`, when given, is called with the recognized location for a file right before
    it would be tagged; returning `False` skips writing the tag for that file. It runs
    synchronously on the single worker thread, so it's safe to block on user input there.
    Ignored when `dry_run` is set, since nothing would be written anyway.

    On startup, every file already sitting in `input_dir` is queued up too - `watchdog` only
    reports files that appear *after* it starts watching.

    Blocks until `stop_event` is set (e.g. by a Ctrl+C handler in the caller).
    """
    work_queue: "queue.Queue[Path]" = queue.Queue()

    handler = _MediaFileHandler(work_queue)
    observer = Observer()
    observer.schedule(handler, str(input_dir), recursive=True)
    observer.start()

    for path in iter_media_files(input_dir):
        work_queue.put(path)

    worker_thread = threading.Thread(
        target=_worker, args=(work_queue, recognizer, log, stop_event, dry_run, confirm_fn), daemon=True
    )
    worker_thread.start()

    try:
        stop_event.wait()
    finally:
        observer.stop()
        observer.join()
        worker_thread.join(timeout=5)
