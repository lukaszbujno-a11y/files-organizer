from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class FaceEmbedder(ABC):
    @abstractmethod
    def embed(self, face_image: Any) -> Any:
        """Turn a cropped face image into a fixed-size embedding vector (numpy array)."""
        ...


class DeepFaceEmbedder(FaceEmbedder):
    def __init__(self, model_name: str = "Facenet"):
        self.model_name = model_name

    def embed(self, face_image: Any) -> Any:
        import numpy as np
        from deepface import DeepFace

        # DeepFace.extract_faces returns faces as float pixels in [0, 1]; represent()
        # expects the [0, 255] uint8 range it would get from reading a file itself.
        face_uint8 = (face_image * 255).astype("uint8") if face_image.dtype != "uint8" else face_image

        result = DeepFace.represent(
            img_path=face_uint8,
            model_name=self.model_name,
            detector_backend="skip",
            enforce_detection=False,
        )
        return np.array(result[0]["embedding"])
