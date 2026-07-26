from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .exif_reader import SUPPORTED_SUFFIXES
from .face_recognizers import FaceRecognizer
from .metadata import write_tags

LogFn = Callable[[str], None]


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


def _process_one(path: Path, recognizer: FaceRecognizer, log: LogFn, dry_run: bool) -> None:
    if not path.exists():
        return

    log(f"Analizuję: {path}")
    try:
        people = recognizer.recognize(path)
    except Exception as exc:
        log(f"{path} -> błąd rozpoznawania twarzy: {exc}")
        return

    if not people:
        log(f"{path} -> nie rozpoznano znanych osób")
        return
    names = [person.name for person in people]
    if dry_run:
        log(f"{path} -> (dry-run) oznaczono by tagiem: {', '.join(names)}")
        return
    write_tags(path, names)
    log(f"{path} -> {', '.join(names)}")


def _worker(
    work_queue: "queue.Queue[Path]", recognizer: FaceRecognizer, log: LogFn, stop_event: threading.Event, dry_run: bool
) -> None:
    while not stop_event.is_set():
        try:
            path = work_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        try:
            _process_one(path, recognizer, log, dry_run)
        finally:
            work_queue.task_done()


def watch_for_faces(
    input_dir: Path, recognizer: FaceRecognizer, log: LogFn, stop_event: threading.Event, dry_run: bool = False
) -> None:
    """Long-running: watch `input_dir` for new media files and tag recognized people on them.

    Independent of `run_pipeline` - meant to keep running in the background while the user
    copies photos into `input_dir`, tagging each new file as it lands. Face recognition never
    runs inside the watchdog callback itself: `watchdog` only pushes paths onto a queue, and a
    separate worker thread drains it, so copying in hundreds of files at once queues up cheaply
    instead of blocking the OS event thread.

    `dry_run` still runs detection/recognition but skips `write_tags`, logging what would have
    been tagged instead - useful for checking `known_faces` enrollment before touching real files.

    Blocks until `stop_event` is set (e.g. by a Ctrl+C handler in the caller).
    """
    work_queue: "queue.Queue[Path]" = queue.Queue()

    handler = _MediaFileHandler(work_queue)
    observer = Observer()
    observer.schedule(handler, str(input_dir), recursive=True)
    observer.start()

    worker_thread = threading.Thread(
        target=_worker, args=(work_queue, recognizer, log, stop_event, dry_run), daemon=True
    )
    worker_thread.start()

    try:
        stop_event.wait()
    finally:
        observer.stop()
        observer.join()
        worker_thread.join(timeout=5)
