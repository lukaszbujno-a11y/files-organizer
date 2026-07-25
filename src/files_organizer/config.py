from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class PhoneMappingEntry:
    camera_model: str
    parent_dir: str


@dataclass(frozen=True)
class Config:
    input_dir: Path
    output_dir: Path | None
    calendar: dict | None = None
    mode: str = "copy"
    margin_hours: float = 2
    unmatched_dir_name: str = "Nieprzypisane"
    overlap_dir_name: str = "Niedopasowane"
    phone_mapping: dict[str, PhoneMappingEntry] = field(default_factory=dict)
    include_tags: list[str] | None = None

    def __post_init__(self):
        if self.mode not in {"copy", "move"}:
            raise ValueError(f"mode must be 'copy' or 'move', got {self.mode!r}")


def default_config(base_dir: str | Path | None = None) -> Config:
    """Config used when no config file is found: operate on the current directory."""
    base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
    return Config(input_dir=base_dir, output_dir=base_dir / "output")


def load_config(path: str | Path) -> Config:
    path = Path(path)
    if not path.exists():
        return default_config()

    raw = yaml.safe_load(path.read_text())

    phone_mapping = {
        tag: PhoneMappingEntry(camera_model=entry["camera_model"], parent_dir=entry["parent_dir"])
        for tag, entry in (raw.get("phone_mapping") or {}).items()
    }

    output_dir = raw.get("output_dir")

    return Config(
        input_dir=Path(raw["input_dir"]),
        output_dir=Path(output_dir) if output_dir is not None else None,
        calendar=raw.get("calendar"),
        mode=raw.get("mode", "copy"),
        margin_hours=raw.get("margin_hours", 2),
        unmatched_dir_name=raw.get("unmatched_dir_name", "Nieprzypisane"),
        overlap_dir_name=raw.get("overlap_dir_name", "Niedopasowane"),
        phone_mapping=phone_mapping,
        include_tags=raw.get("include_tags"),
    )
