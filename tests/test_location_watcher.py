import threading
import time

from PIL import Image

from files_organizer.location_recognizers.base import LocationRecognizer
from files_organizer.location_watcher import scan_for_locations, watch_for_locations
from files_organizer.metadata import read_tagged_countries, read_tagged_locations, write_location_tags
from files_organizer.models import RecognizedLocation

ZAKOPANE = RecognizedLocation(city="Zakopane", country="Poland", latitude=49.3, longitude=19.9)


class FakeRecognizer(LocationRecognizer):
    def __init__(self, location: RecognizedLocation | None):
        self.location = location
        self.paths = []

    def recognize(self, path):
        self.paths.append(path)
        return self.location


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
        target=watch_for_locations,
        args=(input_dir, recognizer, log or (lambda msg: None), stop_event),
        kwargs={"dry_run": dry_run, "confirm_fn": confirm_fn},
        daemon=True,
    )
    watcher_thread.start()
    time.sleep(0.3)  # let the observer start watching before any file appears
    return watcher_thread


def test_watch_for_locations_tags_photo_already_present_at_startup(tmp_path):
    photo = tmp_path / "existing.jpg"
    _make_jpeg(photo)

    recognizer = FakeRecognizer(ZAKOPANE)
    stop_event = threading.Event()
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event)

    try:
        assert _wait_until(
            lambda: read_tagged_locations(photo) == ["Zakopane"] and read_tagged_countries(photo) == ["Poland"]
        )
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_locations_tags_new_photo(tmp_path):
    recognizer = FakeRecognizer(ZAKOPANE)
    stop_event = threading.Event()
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event)

    try:
        photo = tmp_path / "new.jpg"
        _make_jpeg(photo)

        assert _wait_until(lambda: read_tagged_locations(photo) == ["Zakopane"])
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_locations_ignores_unsupported_files(tmp_path):
    recognizer = FakeRecognizer(ZAKOPANE)
    stop_event = threading.Event()
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event)

    try:
        (tmp_path / "notes.txt").write_text("not a photo")
        time.sleep(0.5)

        assert recognizer.paths == []
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_locations_dry_run_does_not_write_tags(tmp_path):
    recognizer = FakeRecognizer(ZAKOPANE)
    stop_event = threading.Event()
    log_messages: list[str] = []
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event, log=log_messages.append, dry_run=True)

    try:
        photo = tmp_path / "new.jpg"
        _make_jpeg(photo)

        assert _wait_until(lambda: any("dry-run" in message and "Zakopane" in message for message in log_messages))
        assert read_tagged_locations(photo) == []
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_locations_writes_tag_when_confirmed(tmp_path):
    recognizer = FakeRecognizer(ZAKOPANE)
    stop_event = threading.Event()
    confirm_calls = []

    def confirm_fn(path, location):
        confirm_calls.append((path, location))
        return True

    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event, confirm_fn=confirm_fn)

    try:
        photo = tmp_path / "new.jpg"
        _make_jpeg(photo)

        assert _wait_until(lambda: read_tagged_locations(photo) == ["Zakopane"])
        assert (photo, ZAKOPANE) in confirm_calls
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_locations_skips_tag_when_rejected(tmp_path):
    recognizer = FakeRecognizer(ZAKOPANE)
    stop_event = threading.Event()
    log_messages: list[str] = []
    watcher_thread = _run_watcher(
        tmp_path, recognizer, stop_event, log=log_messages.append, confirm_fn=lambda path, location: False
    )

    try:
        photo = tmp_path / "new.jpg"
        _make_jpeg(photo)

        assert _wait_until(lambda: len(recognizer.paths) == 1)
        assert read_tagged_locations(photo) == []
        assert any("pominięto" in message and "Zakopane" in message for message in log_messages)
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_locations_skips_files_without_gps(tmp_path):
    recognizer = FakeRecognizer(None)
    stop_event = threading.Event()
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event)

    try:
        photo = tmp_path / "no_gps.jpg"
        _make_jpeg(photo)

        assert _wait_until(lambda: len(recognizer.paths) == 1)
        assert read_tagged_locations(photo) == []
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_watch_for_locations_skips_already_tagged_photo_without_recognizing(tmp_path):
    photo = tmp_path / "existing.jpg"
    _make_jpeg(photo)
    write_location_tags(photo, ZAKOPANE)

    recognizer = FakeRecognizer(RecognizedLocation(city="Kraków", country="Poland", latitude=50.06, longitude=19.94))
    stop_event = threading.Event()
    watcher_thread = _run_watcher(tmp_path, recognizer, stop_event)

    try:
        photo_b = tmp_path / "new.jpg"
        _make_jpeg(photo_b)
        assert _wait_until(lambda: read_tagged_locations(photo_b) == ["Kraków"])

        assert photo not in recognizer.paths
        assert read_tagged_locations(photo) == ["Zakopane"]
    finally:
        stop_event.set()
        watcher_thread.join(timeout=5)


def test_scan_for_locations_returns_detections_without_writing_tags(tmp_path):
    photo_a = tmp_path / "a.jpg"
    photo_b = tmp_path / "b.jpg"
    _make_jpeg(photo_a)
    _make_jpeg(photo_b)

    recognizer = FakeRecognizer(ZAKOPANE)

    detections = scan_for_locations(tmp_path, recognizer, log=lambda msg: None)

    assert {d.path for d in detections} == {photo_a, photo_b}
    assert all(d.location == ZAKOPANE for d in detections)
    assert read_tagged_locations(photo_a) == []
    assert read_tagged_locations(photo_b) == []


def test_scan_for_locations_stops_after_reaching_limit(tmp_path):
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        _make_jpeg(tmp_path / name)

    recognizer = FakeRecognizer(ZAKOPANE)
    log_messages: list[str] = []

    detections = scan_for_locations(tmp_path, recognizer, log=log_messages.append, limit=2)

    assert len(detections) == 2
    assert len(recognizer.paths) == 2
    assert any("limit" in message for message in log_messages)


def test_scan_for_locations_without_limit_scans_everything(tmp_path):
    for name in ("a.jpg", "b.jpg", "c.jpg"):
        _make_jpeg(tmp_path / name)

    recognizer = FakeRecognizer(ZAKOPANE)

    detections = scan_for_locations(tmp_path, recognizer, log=lambda msg: None)

    assert len(detections) == 3


def test_scan_for_locations_skips_already_tagged_photo_without_recognizing(tmp_path):
    tagged_photo = tmp_path / "tagged.jpg"
    untagged_photo = tmp_path / "untagged.jpg"
    _make_jpeg(tagged_photo)
    _make_jpeg(untagged_photo)
    write_location_tags(tagged_photo, ZAKOPANE)

    recognizer = FakeRecognizer(RecognizedLocation(city="Kraków", country="Poland", latitude=50.06, longitude=19.94))
    log_messages: list[str] = []

    detections = scan_for_locations(tmp_path, recognizer, log=log_messages.append)

    assert {d.path for d in detections} == {untagged_photo}
    assert recognizer.paths == [untagged_photo]
    assert any("pomijam" in message and "tagged.jpg" in message for message in log_messages)


def test_scan_for_locations_skips_files_without_gps(tmp_path):
    photo = tmp_path / "no_gps.jpg"
    _make_jpeg(photo)

    recognizer = FakeRecognizer(None)

    detections = scan_for_locations(tmp_path, recognizer, log=lambda msg: None)

    assert detections == []


def test_scan_for_locations_logs_and_continues_after_recognition_error(tmp_path):
    good_photo = tmp_path / "good.jpg"
    bad_photo = tmp_path / "bad.jpg"
    _make_jpeg(good_photo)
    _make_jpeg(bad_photo)

    class FlakyRecognizer(LocationRecognizer):
        def recognize(self, path):
            if path == bad_photo:
                raise RuntimeError("boom")
            return ZAKOPANE

    log_messages: list[str] = []
    detections = scan_for_locations(tmp_path, FlakyRecognizer(), log=log_messages.append)

    assert [d.path for d in detections] == [good_photo]
    assert any("błąd rozpoznawania lokalizacji" in message for message in log_messages)
