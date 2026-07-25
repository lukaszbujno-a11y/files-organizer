from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class FaceEmbedder(ABC):
    @abstractmethod
    def embed(self, face_image: Any) -> Any:
        """Turn a cropped face image into a fixed-size embedding vector (numpy array)."""
        ...


class InsightFaceEmbedder(FaceEmbedder):
    """Reads the embedding insightface's `FaceAnalysis.get()` already computed.

    Detection and recognition run together in one insightface call (see
    `InsightFaceDetector`), so `face_image` here is the insightface `Face` object
    itself rather than pixels - there's nothing left to compute.
    """

    def embed(self, face_image: Any) -> Any:
        return face_image.normed_embedding
