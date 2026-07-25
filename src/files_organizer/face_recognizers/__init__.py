from .base import FaceRecognizer
from .insightface_recognizer import InsightFaceRecognizer

__all__ = ["FaceRecognizer", "InsightFaceRecognizer", "get_face_recognizer"]


def get_face_recognizer(config: dict) -> FaceRecognizer:
    recognizer_type = config.get("type", "insightface")

    if recognizer_type == "insightface":
        return InsightFaceRecognizer(
            known_faces_dir=config["known_faces_dir"],
            cache_path=config.get("cache_path"),
            threshold=config.get("threshold", 0.4),
        )

    raise ValueError(f"Unknown face_recognition type: {recognizer_type!r}")
