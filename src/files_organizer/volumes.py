from __future__ import annotations

from pathlib import Path


def missing_volume(path: Path) -> Path | None:
    """If path lives on an unmounted macOS external volume (/Volumes/<name>), return that volume's path."""
    parts = path.parts
    if len(parts) >= 3 and parts[0] == "/" and parts[1] == "Volumes":
        volume = Path(parts[0], parts[1], parts[2])
        if not volume.exists():
            return volume
    return None
