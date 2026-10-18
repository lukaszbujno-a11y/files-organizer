from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Every classification rule `rules.classify_photos` knows, in their default priority order.
ALL_RULES = ("calendar", "location", "date")


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
    face_recognition: dict | None = None
    location_recognition: dict | None = None
    # Classification rules tried in order; the first one that places a photo wins.
    rules: tuple[str, ...] = ("calendar",)
    home_country: str | None = None
    # A day gets its own date-only folder only when MORE than this many photos reach the date rule.
    date_group_threshold: int = 5

    def __post_init__(self):
        if self.mode not in {"copy", "move"}:
            raise ValueError(f"mode must be 'copy' or 'move', got {self.mode!r}")
        unknown = [rule for rule in self.rules if rule not in ALL_RULES]
        if unknown:
            raise ValueError(f"unknown rules {unknown!r}, expected some of {list(ALL_RULES)!r}")
        if len(set(self.rules)) != len(self.rules):
            raise ValueError(f"rules must not repeat, got {list(self.rules)!r}")
        if self.date_group_threshold < 0:
            raise ValueError(f"date_group_threshold must be >= 0, got {self.date_group_threshold!r}")


def with_rule_enabled(rules: tuple[str, ...], rule: str, enabled: bool) -> tuple[str, ...]:
    """Turn `rule` on or off in `rules`, keeping the configured order of the others.

    A newly enabled rule is inserted where it sits in the default `ALL_RULES` order relative to
    the rules already present, e.g. enabling `location` in `(calendar, date)` gives
    `(calendar, location, date)`.
    """
    if not enabled:
        return tuple(r for r in rules if r != rule)
    if rule in rules:
        return rules
    rank = ALL_RULES.index(rule)
    position = next((i for i, r in enumerate(rules) if ALL_RULES.index(r) > rank), len(rules))
    return rules[:position] + (rule,) + rules[position:]


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
        face_recognition=raw.get("face_recognition"),
        location_recognition=raw.get("location_recognition"),
        rules=tuple(raw.get("rules") or ("calendar",)),
        home_country=raw.get("home_country"),
        date_group_threshold=raw.get("date_group_threshold", 5),
    )
