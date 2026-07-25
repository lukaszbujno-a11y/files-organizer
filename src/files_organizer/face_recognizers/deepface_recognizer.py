from __future__ import annotations

from pathlib import Path

from ..models import RecognizedPerson
from .base import FaceRecognizer
from .detector import DeepFaceDetector, FaceDetector
from .embedder import DeepFaceEmbedder, FaceEmbedder
from .known_faces_index import KnownFacesIndex


class DeepFaceRecognizer(FaceRecognizer):
    """Default FaceRecognizer: detection, embedding and known-faces matching all via deepface.

    The three stages (FaceDetector, FaceEmbedder, KnownFacesIndex) are independently
    swappable - only this class knows they're all backed by deepface today.
    """

    def __init__(
        self,
        known_faces_dir: str | Path,
        cache_path: str | Path | None = None,
        threshold: float = 0.4,
        detector: FaceDetector | None = None,
        embedder: FaceEmbedder | None = None,
    ):
        self.detector = detector or DeepFaceDetector()
        self.embedder = embedder or DeepFaceEmbedder()
        self.index = KnownFacesIndex(
            known_faces_dir,
            detector=self.detector,
            embedder=self.embedder,
            cache_path=cache_path,
            threshold=threshold,
        )

    def recognize(self, path: Path) -> list[RecognizedPerson]:
        results = []
        for face in self.detector.detect(path):
            embedding = self.embedder.embed(face.image)
            match = self.index.identify(embedding)
            if match is None:
                continue
            name, confidence = match
            results.append(RecognizedPerson(name=name, confidence=confidence, bbox=face.bbox))
        return results
