from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

from .detector import FaceDetector
from .embedder import FaceEmbedder

_REFERENCE_SUFFIXES = {".jpg", ".jpeg", ".png"}


class KnownFacesIndex:
    """Enrollment database of known people, built from `known_faces_dir/<Person>/*.jpg`.

    Reference-photo embeddings are expensive to compute (detection + embedding per
    image), so they're cached to disk keyed by each reference file's mtime. On
    construction only reference photos that are new or changed since the cache was
    written get re-embedded; unchanged people cost nothing to load.
    """

    def __init__(
        self,
        known_faces_dir: str | Path,
        detector: FaceDetector,
        embedder: FaceEmbedder,
        cache_path: str | Path | None = None,
        threshold: float = 0.4,
    ):
        self.known_faces_dir = Path(known_faces_dir)
        self.detector = detector
        self.embedder = embedder
        self.cache_path = Path(cache_path) if cache_path is not None else self.known_faces_dir / "cache" / "embeddings.pkl"
        self.threshold = threshold

        # person -> reference image path -> (mtime, embedding)
        self._cache: dict[str, dict[str, tuple[float, Any]]] = {}
        self._load_cache()
        self.refresh()

    def refresh(self) -> None:
        """Re-scan `known_faces_dir`, embedding only reference photos that are new or changed."""
        if not self.known_faces_dir.is_dir():
            return

        changed = False
        seen_people = set()

        for person_dir in sorted(p for p in self.known_faces_dir.iterdir() if p.is_dir()):
            if person_dir == self.cache_path.parent:
                continue  # skip the cache directory itself
            person = person_dir.name
            seen_people.add(person)

            person_cache = self._cache.setdefault(person, {})
            seen_files = set()
            for image_path in sorted(person_dir.iterdir()):
                if image_path.suffix.lower() not in _REFERENCE_SUFFIXES:
                    continue
                key = str(image_path)
                seen_files.add(key)
                mtime = image_path.stat().st_mtime
                cached = person_cache.get(key)
                if cached is not None and cached[0] == mtime:
                    continue

                embedding = self._embed_reference(image_path)
                if embedding is None:
                    person_cache.pop(key, None)
                else:
                    person_cache[key] = (mtime, embedding)
                changed = True

            for stale_key in set(person_cache) - seen_files:
                del person_cache[stale_key]
                changed = True

        for stale_person in set(self._cache) - seen_people:
            del self._cache[stale_person]
            changed = True

        if changed:
            self._save_cache()

    def identify(self, embedding: Any) -> tuple[str, float] | None:
        """Return `(name, confidence)` for the closest known person within `threshold`, else None."""
        best_person: str | None = None
        best_distance: float | None = None

        for person, references in self._cache.items():
            for _mtime, reference_embedding in references.values():
                distance = _cosine_distance(embedding, reference_embedding)
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_person = person

        if best_person is None or best_distance is None or best_distance > self.threshold:
            return None
        return best_person, max(0.0, 1.0 - best_distance)

    def _embed_reference(self, image_path: Path) -> Any | None:
        faces = self.detector.detect(image_path)
        if not faces:
            return None
        return self.embedder.embed(faces[0].image)

    def _load_cache(self) -> None:
        if not self.cache_path.exists():
            return
        try:
            with self.cache_path.open("rb") as f:
                self._cache = pickle.load(f)
        except (pickle.PickleError, EOFError, ValueError, AttributeError):
            self._cache = {}

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_path.open("wb") as f:
            pickle.dump(self._cache, f)


def _cosine_distance(a: Any, b: Any) -> float:
    import numpy as np

    a, b = np.asarray(a), np.asarray(b)
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 1.0
    return 1.0 - float(np.dot(a, b) / denom)
