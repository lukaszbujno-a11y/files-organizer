import pytest

from files_organizer.face_recognizers import InsightFaceRecognizer, get_face_recognizer


def test_get_face_recognizer_returns_insightface_recognizer(tmp_path):
    recognizer = get_face_recognizer({"type": "insightface", "known_faces_dir": str(tmp_path / "known_faces")})

    assert isinstance(recognizer, InsightFaceRecognizer)


def test_get_face_recognizer_defaults_to_insightface(tmp_path):
    recognizer = get_face_recognizer({"known_faces_dir": str(tmp_path / "known_faces")})

    assert isinstance(recognizer, InsightFaceRecognizer)


def test_get_face_recognizer_rejects_unknown_type(tmp_path):
    with pytest.raises(ValueError):
        get_face_recognizer({"type": "unknown", "known_faces_dir": str(tmp_path)})
