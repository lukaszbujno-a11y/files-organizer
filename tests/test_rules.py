from datetime import datetime
from pathlib import Path

from files_organizer.config import Config
from files_organizer.location_recognizers import LocationRecognizer
from files_organizer.matcher import MatchStatus
from files_organizer.models import Event, Photo, RecognizedLocation
from files_organizer.rules import classify_photos

SPLIT = RecognizedLocation(city="Split", country="Croatia", latitude=43.5, longitude=16.4)
KRAKOW = RecognizedLocation(city="Kraków", country="Poland", latitude=50.0, longitude=19.9)


class FakeLocationRecognizer(LocationRecognizer):
    def __init__(self, locations: dict[str, RecognizedLocation]):
        self.locations = locations

    def recognize(self, path: Path) -> RecognizedLocation | None:
        return self.locations.get(path.name)


def make_config(tmp_path: Path, **overrides) -> Config:
    defaults = dict(input_dir=tmp_path / "input", output_dir=tmp_path / "output")
    defaults.update(overrides)
    return Config(**defaults)


def photos_on(day: datetime, count: int, prefix: str = "IMG") -> list[Photo]:
    return [Photo(path=Path(f"{prefix}_{i}.jpg"), taken_at=day.replace(hour=10, minute=i)) for i in range(count)]


def statuses(results) -> list[MatchStatus]:
    return [match.status for _, match in results]


def test_default_rules_only_use_calendar(tmp_path):
    config = make_config(tmp_path)

    results = classify_photos(photos_on(datetime(2026, 7, 15), 10), config, events=[])

    assert statuses(results) == [MatchStatus.UNMATCHED] * 10


def test_date_rule_groups_day_with_more_than_threshold_photos(tmp_path):
    config = make_config(tmp_path, rules=("calendar", "date"), date_group_threshold=5)

    results = classify_photos(photos_on(datetime(2026, 7, 15), 6), config, events=[])

    assert statuses(results) == [MatchStatus.DATE_GROUP] * 6


def test_date_rule_skips_day_with_exactly_threshold_photos(tmp_path):
    config = make_config(tmp_path, rules=("calendar", "date"), date_group_threshold=5)

    results = classify_photos(photos_on(datetime(2026, 7, 15), 5), config, events=[])

    assert statuses(results) == [MatchStatus.UNMATCHED] * 5


def test_photos_placed_by_calendar_do_not_count_towards_date_threshold(tmp_path):
    config = make_config(tmp_path, rules=("calendar", "date"), date_group_threshold=5, margin_hours=0)
    event = Event(name="Obiad", start=datetime(2026, 7, 15, 10, 0), end=datetime(2026, 7, 15, 10, 1))
    # minutes 0-1 hit the event (margin 0), the remaining 5 don't exceed the threshold
    photos = photos_on(datetime(2026, 7, 15), 7)

    results = classify_photos(photos, config, events=[event])

    assert statuses(results) == [MatchStatus.MATCHED] * 2 + [MatchStatus.UNMATCHED] * 5


def test_date_rule_counts_each_day_separately(tmp_path):
    config = make_config(tmp_path, rules=("date",), date_group_threshold=5)
    photos = photos_on(datetime(2026, 7, 15), 6, "A") + photos_on(datetime(2026, 7, 16), 3, "B")

    results = classify_photos(photos, config, events=[])

    assert statuses(results) == [MatchStatus.DATE_GROUP] * 6 + [MatchStatus.UNMATCHED] * 3


def test_photo_without_date_is_never_date_grouped(tmp_path):
    config = make_config(tmp_path, rules=("date",), date_group_threshold=0)

    results = classify_photos([Photo(path=Path("x.jpg"), taken_at=None)], config, events=[])

    assert statuses(results) == [MatchStatus.UNMATCHED]


def test_location_rule_places_photos_outside_home_country(tmp_path):
    config = make_config(tmp_path, rules=("calendar", "location"), home_country="poland")
    photos = photos_on(datetime(2026, 7, 15), 3)
    recognizer = FakeLocationRecognizer({"IMG_0.jpg": SPLIT, "IMG_1.jpg": KRAKOW})

    results = classify_photos(photos, config, events=[], location_recognizer=recognizer)

    assert statuses(results) == [MatchStatus.LOCATION, MatchStatus.UNMATCHED, MatchStatus.UNMATCHED]
    assert results[0][1].location == SPLIT


def test_calendar_takes_priority_over_location(tmp_path):
    config = make_config(tmp_path, rules=("calendar", "location"))
    event = Event(name="Wakacje", start=datetime(2026, 7, 15, 9), end=datetime(2026, 7, 15, 18))
    recognizer = FakeLocationRecognizer({"IMG_0.jpg": SPLIT})

    results = classify_photos(photos_on(datetime(2026, 7, 15), 1), config, events=[event], location_recognizer=recognizer)

    assert statuses(results) == [MatchStatus.MATCHED]


def test_date_before_location_falls_back_to_location_on_small_days(tmp_path):
    config = make_config(tmp_path, rules=("date", "location"), date_group_threshold=5)
    recognizer = FakeLocationRecognizer({"IMG_0.jpg": SPLIT})

    results = classify_photos(photos_on(datetime(2026, 7, 15), 2), config, events=[], location_recognizer=recognizer)

    assert statuses(results) == [MatchStatus.LOCATION, MatchStatus.UNMATCHED]


def test_location_placed_photos_do_not_count_towards_date_threshold(tmp_path):
    config = make_config(tmp_path, rules=("location", "date"), date_group_threshold=5)
    recognizer = FakeLocationRecognizer({"IMG_0.jpg": SPLIT})

    results = classify_photos(photos_on(datetime(2026, 7, 15), 6), config, events=[], location_recognizer=recognizer)

    assert statuses(results) == [MatchStatus.LOCATION] + [MatchStatus.UNMATCHED] * 5


def test_unreachable_geocoder_aborts_classification(tmp_path):
    import pytest

    from files_organizer.location_recognizers import GeocoderUnavailableError

    class OfflineRecognizer(LocationRecognizer):
        def recognize(self, path):
            raise GeocoderUnavailableError("offline")

    config = make_config(tmp_path, rules=("location", "date"))

    with pytest.raises(GeocoderUnavailableError):
        classify_photos(photos_on(datetime(2026, 7, 15), 1), config, events=[], location_recognizer=OfflineRecognizer())
