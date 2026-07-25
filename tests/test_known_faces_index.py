import os
from pathlib import Path

import numpy as np

from files_organizer.face_recognizers.detector import DetectedFace, FaceDetector
from files_organizer.face_recognizers.embedder import FaceEmbedder
from files_organizer.face_recognizers.known_faces_index import KnownFacesIndex


class FakeDetector(FaceDetector):
    """Treats a reference photo's raw bytes as its one "face", so tests can control
    embeddings deterministically without a real detection/embedding model."""

    def __init__(self):
        self.calls: list[Path] = []

    def detect(self, path):
        self.calls.append(path)
        return [DetectedFace(bbox=(0, 0, 1, 1), image=path.read_bytes())]


class FakeEmbedder(FaceEmbedder):
    def embed(self, face_image: bytes):
        return np.frombuffer(face_image.ljust(8, b"\0")[:8], dtype=np.uint8).astype(float)


def _make_known_faces(known_faces_dir: Path) -> None:
    (known_faces_dir / "Anna").mkdir(parents=True)
    (known_faces_dir / "Anna" / "1.jpg").write_bytes(b"anna-ref")

    (known_faces_dir / "Bartek").mkdir(parents=True)
    (known_faces_dir / "Bartek" / "1.jpg").write_bytes(b"bartek-ref")


def test_identify_returns_closest_known_person(tmp_path):
    known_faces_dir = tmp_path / "known_faces"
    _make_known_faces(known_faces_dir)
    embedder = FakeEmbedder()
    index = KnownFacesIndex(known_faces_dir, detector=FakeDetector(), embedder=embedder, threshold=0.01)

    match = index.identify(embedder.embed(b"anna-ref"))

    assert match is not None
    name, confidence = match
    assert name == "Anna"
    assert confidence > 0.99


def test_identify_returns_none_when_no_match_within_threshold(tmp_path):
    known_faces_dir = tmp_path / "known_faces"
    _make_known_faces(known_faces_dir)
    embedder = FakeEmbedder()
    index = KnownFacesIndex(known_faces_dir, detector=FakeDetector(), embedder=embedder, threshold=0.0001)

    assert index.identify(embedder.embed(b"someone-else")) is None


def test_second_construction_reuses_cache_without_recomputing(tmp_path):
    known_faces_dir = tmp_path / "known_faces"
    _make_known_faces(known_faces_dir)
    embedder = FakeEmbedder()

    first_detector = FakeDetector()
    KnownFacesIndex(known_faces_dir, detector=first_detector, embedder=embedder)
    assert len(first_detector.calls) == 2  # Anna + Bartek reference photos

    second_detector = FakeDetector()
    KnownFacesIndex(known_faces_dir, detector=second_detector, embedder=embedder)

    assert second_detector.calls == []


def test_cache_recomputes_only_changed_reference_photo(tmp_path):
    known_faces_dir = tmp_path / "known_faces"
    _make_known_faces(known_faces_dir)
    embedder = FakeEmbedder()
    KnownFacesIndex(known_faces_dir, detector=FakeDetector(), embedder=embedder)

    anna_photo = known_faces_dir / "Anna" / "1.jpg"
    anna_photo.write_bytes(b"anna-ref-updated")
    bumped_mtime = anna_photo.stat().st_mtime + 5
    os.utime(anna_photo, (bumped_mtime, bumped_mtime))

    detector = FakeDetector()
    KnownFacesIndex(known_faces_dir, detector=detector, embedder=embedder)

    assert detector.calls == [anna_photo]


def test_new_person_added_after_construction_is_picked_up_on_refresh(tmp_path):
    known_faces_dir = tmp_path / "known_faces"
    _make_known_faces(known_faces_dir)
    embedder = FakeEmbedder()
    index = KnownFacesIndex(known_faces_dir, detector=FakeDetector(), embedder=embedder, threshold=0.01)

    (known_faces_dir / "Celina").mkdir()
    (known_faces_dir / "Celina" / "1.jpg").write_bytes(b"celina-ref")
    index.refresh()

    match = index.identify(embedder.embed(b"celina-ref"))
    assert match is not None
    assert match[0] == "Celina"
