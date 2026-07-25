import pytest

from files_organizer.face_recognizers import DeepFaceRecognizer, get_face_recognizer


def test_get_face_recognizer_returns_deepface_recognizer(tmp_path):
    recognizer = get_face_recognizer({"type": "deepface", "known_faces_dir": str(tmp_path / "known_faces")})

    assert isinstance(recognizer, DeepFaceRecognizer)


def test_get_face_recognizer_defaults_to_deepface(tmp_path):
    recognizer = get_face_recognizer({"known_faces_dir": str(tmp_path / "known_faces")})

    assert isinstance(recognizer, DeepFaceRecognizer)


def test_get_face_recognizer_rejects_unknown_type(tmp_path):
    with pytest.raises(ValueError):
        get_face_recognizer({"type": "unknown", "known_faces_dir": str(tmp_path)})
