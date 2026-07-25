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


class InsightFaceDetector(FaceDetector):
    """Locates faces using insightface's `buffalo_l` pack (RetinaFace detector).

    Only the `detection` and `recognition` sub-models are loaded (`allowed_modules`) -
    the pack also ships age/gender and 3D landmark models we don't need, and skipping
    them keeps load and per-image inference lighter.

    insightface computes detection and the recognition embedding in a single `get()`
    call (the embedding step needs the detector's landmarks to align the crop), so
    there's no separate "crop out a face" step the way deepface has - `image` on the
    returned `DetectedFace` is the whole insightface `Face` object, embedding already
    included. `InsightFaceEmbedder.embed()` just reads it back off.
    """

    def __init__(self, model_name: str = "buffalo_l", det_size: tuple[int, int] = (640, 640)):
        self.model_name = model_name
        self.det_size = det_size
        self._app = None

    def detect(self, path: Path) -> list[DetectedFace]:
        import cv2

        image = cv2.imread(str(path))
        if image is None:
            return []

        detected = []
        for face in self._get_app().get(image):
            x1, y1, x2, y2 = (int(round(v)) for v in face.bbox)
            detected.append(DetectedFace(bbox=(x1, y1, x2 - x1, y2 - y1), image=face))
        return detected

    def _get_app(self):
        if self._app is None:
            from insightface.app import FaceAnalysis

            app = FaceAnalysis(
                name=self.model_name,
                providers=["CPUExecutionProvider"],
                allowed_modules=["detection", "recognition"],
            )
            app.prepare(ctx_id=0, det_size=self.det_size)
            self._app = app
        return self._app
