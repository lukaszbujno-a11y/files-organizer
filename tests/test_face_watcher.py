import threading
import time

from PIL import Image

from files_organizer.face_recognizers.base import FaceRecognizer
from files_organizer.face_watcher import scan_for_faces, watch_for_faces
from files_organizer.metadata import read_tagged_people, write_tags
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


def _run_watcher(input_dir, recognizer, stop_event, log=None, dry_run=False, confirm_fn=None):
    watcher_thread = threading.Thread(
        target=watch_for_faces,
        args=(input_dir, recognizer, log or (lambda msg: None), stop_event),
        kwargs={"dry_run": dry_run, "confirm_fn": confirm_fn},
        daemon=True,
    )
    watcher_thread.start()
    time.sleep(0.3)  # let the observer start watching before any file appears
    return watcher_thread


def test_watch_for_faces_tags_photo_already_present_at_startup(tmp_path):
    photo = tmp_path / "existing.jpg"
    _make_jpeg(photo)

    recognizer = FakeRecognizer([RecognizedPerson(name="Anna", confidence=0.9, bbox=(0, 0, 1, 1))])
    stop_event = threading.Event()
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event)

    try:
        assert _wait_until(lambda: read_tagged_people(photo) == ["Anna"])
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


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


def test_watch_for_faces_dry_run_does_not_write_tags(tmp_path):
    recognizer = FakeRecognizer([RecognizedPerson(name="Anna", confidence=0.9, bbox=(0, 0, 1, 1))])
    stop_event = threading.Event()
    log_messages: list[str] = []
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event, log=log_messages.append, dry_run=True)

    try:
        photo = tmp_path / "new.jpg"
        _make_jpeg(photo)

        assert _wait_until(lambda: len(recognizer.paths) == 1)
        assert any("dry-run" in message and "Anna" in message for message in log_messages)
        assert read_tagged_people(photo) == []
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_faces_writes_tag_when_confirmed(tmp_path):
    recognizer = FakeRecognizer([RecognizedPerson(name="Anna", confidence=0.9, bbox=(0, 0, 1, 1))])
    stop_event = threading.Event()
    confirm_calls = []

    def confirm_fn(path, names):
        confirm_calls.append((path, names))
        return True

    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event, confirm_fn=confirm_fn)

    try:
        photo = tmp_path / "new.jpg"
        _make_jpeg(photo)

        assert _wait_until(lambda: read_tagged_people(photo) == ["Anna"])
        assert (photo, ["Anna"]) in confirm_calls
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_faces_skips_tag_when_rejected(tmp_path):
    recognizer = FakeRecognizer([RecognizedPerson(name="Anna", confidence=0.9, bbox=(0, 0, 1, 1))])
    stop_event = threading.Event()
    log_messages: list[str] = []
    watcher_thread = _run_watcher(
        tmp_path, recognizer, stop_event, log=log_messages.append, confirm_fn=lambda path, names: False
    )

    try:
        photo = tmp_path / "new.jpg"
        _make_jpeg(photo)

        assert _wait_until(lambda: len(recognizer.paths) == 1)
        assert read_tagged_people(photo) == []
        assert any("pominięto" in message and "Anna" in message for message in log_messages)
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


def test_watch_for_faces_skips_photo_already_tagged_with_a_person(tmp_path):
    photo = tmp_path / "existing.jpg"
    _make_jpeg(photo)
    write_tags(photo, ["Anna"])

    recognizer = FakeRecognizer([RecognizedPerson(name="Jan", confidence=0.9, bbox=(0, 0, 1, 1))])
    stop_event = threading.Event()
    log_messages: list[str] = []
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event, log=log_messages.append)

    try:
        assert _wait_until(lambda: any("pominięto" in message for message in log_messages))
        assert recognizer.paths == []
        assert read_tagged_people(photo) == ["Anna"]
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_scan_for_faces_returns_detections_without_writing_tags(tmp_path):
    photo_a = tmp_path / "a.jpg"
    photo_b = tmp_path / "b.jpg"
    _make_jpeg(photo_a)
    _make_jpeg(photo_b)

    recognizer = FakeRecognizer([RecognizedPerson(name="Anna", confidence=0.9, bbox=(0, 0, 1, 1))])

    detections = scan_for_faces(tmp_path, recognizer, log=lambda msg: None)

    assert {d.path for d in detections} == {photo_a, photo_b}
    assert all(d.names == ["Anna"] for d in detections)
    assert read_tagged_people(photo_a) == []
    assert read_tagged_people(photo_b) == []


def test_scan_for_faces_skips_photo_already_tagged_with_a_person(tmp_path):
    tagged_photo = tmp_path / "tagged.jpg"
    untagged_photo = tmp_path / "untagged.jpg"
    _make_jpeg(tagged_photo)
    _make_jpeg(untagged_photo)
    write_tags(tagged_photo, ["Anna"])

    recognizer = FakeRecognizer([RecognizedPerson(name="Jan", confidence=0.9, bbox=(0, 0, 1, 1))])
    log_messages: list[str] = []

    detections = scan_for_faces(tmp_path, recognizer, log=log_messages.append)

    assert [d.path for d in detections] == [untagged_photo]
    assert recognizer.paths == [untagged_photo]
    assert any("pominięto" in message and "tagged.jpg" in message for message in log_messages)


def test_scan_for_faces_skips_files_with_no_recognized_person(tmp_path):
    photo = tmp_path / "stranger.jpg"
    _make_jpeg(photo)

    recognizer = FakeRecognizer([])

    detections = scan_for_faces(tmp_path, recognizer, log=lambda msg: None)

    assert detections == []


def test_scan_for_faces_logs_and_continues_after_recognition_error(tmp_path):
    good_photo = tmp_path / "good.jpg"
    bad_photo = tmp_path / "bad.jpg"
    _make_jpeg(good_photo)
    _make_jpeg(bad_photo)

    class FlakyRecognizer(FaceRecognizer):
        def recognize(self, path):
            if path == bad_photo:
                raise RuntimeError("boom")
            return [RecognizedPerson(name="Anna", confidence=0.9, bbox=(0, 0, 1, 1))]

    log_messages: list[str] = []
    detections = scan_for_faces(tmp_path, FlakyRecognizer(), log=log_messages.append)

    assert [d.path for d in detections] == [good_photo]
    assert any("błąd rozpoznawania twarzy" in message for message in log_messages)
