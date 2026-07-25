from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DetectedFace:
    bbox: tuple[int, int, int, int]  # x, y, width, height
    image: Any  # cropped face pixels (numpy array), ready to hand to a FaceEmbedder


class FaceDetector(ABC):
    @abstractmethod
    def detect(self, path: Path) -> list[DetectedFace]:
        ...


class DeepFaceDetector(FaceDetector):
    """Locates faces in an image using deepface's face-detection backends (e.g. opencv, retinaface)."""

    def __init__(self, detector_backend: str = "opencv"):
        self.detector_backend = detector_backend

    def detect(self, path: Path) -> list[DetectedFace]:
        from deepface import DeepFace

        try:
            faces = DeepFace.extract_faces(
                img_path=str(path),
                detector_backend=self.detector_backend,
                enforce_detection=False,
            )
        except ValueError:
            # deepface raises when it can't decode the file at all (corrupt/unsupported image)
            return []

        detected = []
        for face in faces:
            # enforce_detection=False returns a single low/no-confidence "face" spanning
            # the whole image when nothing was found instead of raising - skip that.
            if face.get("confidence", 1.0) <= 0:
                continue
            area = face["facial_area"]
            detected.append(
                DetectedFace(
                    bbox=(area["x"], area["y"], area["w"], area["h"]),
                    image=face["face"],
                )
            )
        return detected
