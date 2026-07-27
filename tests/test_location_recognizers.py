import pytest

from files_organizer.location_recognizers import ReverseGeocoderRecognizer, get_location_recognizer
from files_organizer.location_recognizers.geocoder import Geocoder


class FakeGeocoder(Geocoder):
    def __init__(self, result: tuple[str, str] | None):
        self.result = result
        self.calls: list[tuple[float, float]] = []

    def lookup(self, latitude, longitude):
        self.calls.append((latitude, longitude))
        return self.result


def test_get_location_recognizer_returns_reverse_geocoder_recognizer():
    recognizer = get_location_recognizer({"type": "reverse_geocoder"})

    assert isinstance(recognizer, ReverseGeocoderRecognizer)


def test_get_location_recognizer_defaults_to_reverse_geocoder():
    recognizer = get_location_recognizer({})

    assert isinstance(recognizer, ReverseGeocoderRecognizer)


def test_get_location_recognizer_rejects_unknown_type():
    with pytest.raises(ValueError):
        get_location_recognizer({"type": "unknown"})


def test_recognize_returns_location_for_known_coordinates(tmp_path):
    path = tmp_path / "photo.jpg"
    geocoder = FakeGeocoder(("Zakopane", "Poland"))
    recognizer = ReverseGeocoderRecognizer(geocoder=geocoder, gps_reader=lambda p: (49.3, 19.9))

    location = recognizer.recognize(path)

    assert location.city == "Zakopane"
    assert location.country == "Poland"
    assert location.latitude == 49.3
    assert location.longitude == 19.9
    assert geocoder.calls == [(49.3, 19.9)]


def test_recognize_returns_none_without_gps_data(tmp_path):
    path = tmp_path / "photo.jpg"
    geocoder = FakeGeocoder(("Zakopane", "Poland"))
    recognizer = ReverseGeocoderRecognizer(geocoder=geocoder, gps_reader=lambda p: None)

    assert recognizer.recognize(path) is None
    assert geocoder.calls == []


def test_recognize_returns_none_when_geocoder_finds_nothing(tmp_path):
    path = tmp_path / "photo.jpg"
    geocoder = FakeGeocoder(None)
    recognizer = ReverseGeocoderRecognizer(geocoder=geocoder, gps_reader=lambda p: (49.3, 19.9))

    assert recognizer.recognize(path) is None
