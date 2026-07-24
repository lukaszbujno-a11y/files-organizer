from datetime import datetime
from pathlib import Path

from files_organizer.config import Config, PhoneMappingEntry
from files_organizer.matcher import MatchResult, MatchStatus
from files_organizer.models import Event, Photo
from files_organizer.organizer import build_target_dir


def make_config(tmp_path: Path, **overrides) -> Config:
    defaults = dict(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        calendar={"type": "ics", "path": "calendar.ics"},
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_matched_photo_goes_to_event_folder(tmp_path):
    config = make_config(tmp_path)
    event = Event(name="Wakacje Chorwacja", start=datetime(2026, 7, 15, 10), end=datetime(2026, 7, 15, 18))
    photo = Photo(path=Path("IMG_1.jpg"), taken_at=datetime(2026, 7, 15, 12))
    match = MatchResult(status=MatchStatus.MATCHED, event=event)

    target = build_target_dir(config, photo, match)

    assert target == config.output_dir / "2026" / "07" / "2026-07-15 Wakacje Chorwacja"


def test_unmatched_photo_goes_to_unmatched_folder(tmp_path):
    config = make_config(tmp_path)
    photo = Photo(path=Path("IMG_2.jpg"), taken_at=datetime(2026, 7, 15, 12))
    match = MatchResult(status=MatchStatus.UNMATCHED)

    target = build_target_dir(config, photo, match)

    assert target == config.output_dir / "Nieprzypisane" / "2026-07"


def test_overlapping_photo_goes_to_overlap_folder(tmp_path):
    config = make_config(tmp_path)
    photo = Photo(path=Path("IMG_3.jpg"), taken_at=datetime(2026, 7, 15, 12))
    match = MatchResult(status=MatchStatus.OVERLAPPING)

    target = build_target_dir(config, photo, match)

    assert target == config.output_dir / "2026" / "07" / "2026-07-15 Niedopasowane"


def test_phone_mapping_adds_parent_dir(tmp_path):
    mapping = {"rodzina": PhoneMappingEntry(camera_model="iPhone 15 Pro", parent_dir="Ania")}
    config = make_config(tmp_path, phone_mapping=mapping)
    event = Event(
        name="Urodziny", start=datetime(2026, 7, 15, 10), end=datetime(2026, 7, 15, 18), tag="rodzina"
    )
    photo = Photo(path=Path("IMG_4.jpg"), taken_at=datetime(2026, 7, 15, 12), camera_model="iPhone 15 Pro")
    match = MatchResult(status=MatchStatus.MATCHED, event=event)

    target = build_target_dir(config, photo, match)

    assert target == config.output_dir / "Ania" / "2026" / "07" / "2026-07-15 Urodziny"
