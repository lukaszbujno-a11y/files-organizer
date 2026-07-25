from .base import FaceRecognizer
from .deepface_recognizer import DeepFaceRecognizer

__all__ = ["FaceRecognizer", "DeepFaceRecognizer", "get_face_recognizer"]


def get_face_recognizer(config: dict) -> FaceRecognizer:
    recognizer_type = config.get("type", "deepface")

    if recognizer_type == "deepface":
        return DeepFaceRecognizer(
            known_faces_dir=config["known_faces_dir"],
            cache_path=config.get("cache_path"),
            threshold=config.get("threshold", 0.4),
        )

    raise ValueError(f"Unknown face_recognition type: {recognizer_type!r}")
