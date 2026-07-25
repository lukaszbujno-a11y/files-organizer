import threading
import time

from PIL import Image

from files_organizer.face_recognizers.base import FaceRecognizer
from files_organizer.face_watcher import watch_for_faces
from files_organizer.metadata import read_tagged_people
from files_organizer.models import RecognizedPerson


class FakeRecognizer(FaceRecognizer):
    def __init__(self, people: list[RecognizedPerson]):
        self.people = people
        self.paths = []

    def recognize(self, path):
        self.paths.append(path)
        return self.people


def _make_jpeg(path):
    Image.new("RGB", (2, 2)).save(path, "JPEG")


def _wait_until(predicate, timeout=5.0, interval=0.05) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def _run_watcher(input_dir, recognizer, stop_event):
    watcher_thread = threading.Thread(
        target=watch_for_faces, args=(input_dir, recognizer, lambda msg: None, stop_event), daemon=True
    )
    watcher_thread.start()
    time.sleep(0.3)  # let the observer start watching before any file appears
    return watcher_thread


def test_watch_for_faces_tags_new_photo(tmp_path):
    recognizer = FakeRecognizer([RecognizedPerson(name="Anna", confidence=0.9, bbox=(0, 0, 1, 1))])
    stop_event = threading.Event()
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event)

    try:
        photo = tmp_path / "new.jpg"
        _make_jpeg(photo)

        assert _wait_until(lambda: read_tagged_people(photo) == ["Anna"])
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_faces_ignores_unsupported_files(tmp_path):
    recognizer = FakeRecognizer([RecognizedPerson(name="Anna", confidence=0.9, bbox=(0, 0, 1, 1))])
    stop_event = threading.Event()
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event)

    try:
        (tmp_path / "notes.txt").write_text("not a photo")
        time.sleep(0.5)

        assert recognizer.paths == []
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_faces_skips_files_with_no_recognized_person(tmp_path):
    recognizer = FakeRecognizer([])
    stop_event = threading.Event()
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event)

    try:
        photo = tmp_path / "stranger.jpg"
        _make_jpeg(photo)

        assert _wait_until(lambda: len(recognizer.paths) == 1)
        assert read_tagged_people(photo) == []
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)
