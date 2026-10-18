import math

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


def test_country_name_is_translated_to_polish():
    pytest.importorskip("pycountry")
    from files_organizer.location_recognizers.geocoder import _country_name

    assert _country_name("HR", "pl") == "Chorwacja"
    assert _country_name("PL", "pl") == "Polska"
    assert _country_name("HR", "en") == "Croatia"


def test_unknown_language_falls_back_to_english():
    pytest.importorskip("pycountry")
    from files_organizer.location_recognizers.geocoder import _country_name

    assert _country_name("HR", "xx") == "Croatia"


def test_get_location_recognizer_passes_language_to_geocoder():
    recognizer = get_location_recognizer({"type": "reverse_geocoder", "language": "en"})

    assert recognizer.geocoder.language == "en"


def make_nominatim(tmp_path, responses: list[dict]):
    from files_organizer.location_recognizers.geocoder import NominatimGeocoder

    calls = []

    def fetch(url, headers):
        calls.append((url, headers))
        return responses[len(calls) - 1]

    geocoder = NominatimGeocoder(cache_path=tmp_path / "cache.json", min_interval=0, fetch=fetch)
    return geocoder, calls


def test_nominatim_returns_localized_city_and_country(tmp_path):
    geocoder, calls = make_nominatim(
        tmp_path, [{"address": {"city": "Wiedeń", "country": "Austria", "country_code": "at"}}]
    )

    assert geocoder.lookup(48.21, 16.37) == ("Wiedeń", "Austria")
    url, headers = calls[0]
    assert "accept-language=pl" in url
    assert headers["User-Agent"].startswith("files-organizer")


def test_nominatim_prefers_settlement_over_municipality(tmp_path):
    geocoder, _ = make_nominatim(
        tmp_path, [{"address": {"municipality": "Львівська міська громада", "city": "Lwów", "country": "Ukraina"}}]
    )

    assert geocoder.lookup(49.84, 24.03) == ("Lwów", "Ukraina")


def test_nominatim_falls_back_to_village(tmp_path):
    geocoder, _ = make_nominatim(
        tmp_path, [{"address": {"village": "Brzegi", "municipality": "gmina Bukowina Tatrzańska", "country": "Polska"}}]
    )

    assert geocoder.lookup(49.2, 20.07) == ("Brzegi", "Polska")


def test_nominatim_returns_none_when_nothing_found(tmp_path):
    geocoder, _ = make_nominatim(tmp_path, [{"error": "Unable to geocode"}])

    assert geocoder.lookup(40.0, -30.0) is None


def test_nominatim_caches_results_on_disk(tmp_path):
    from files_organizer.location_recognizers.geocoder import NominatimGeocoder

    geocoder, calls = make_nominatim(tmp_path, [{"address": {"city": "Kraków", "country": "Polska"}}])
    geocoder.lookup(50.0612, 19.9371)
    # a few metres away - same cache cell, no second request
    assert geocoder.lookup(50.0613, 19.9372) == ("Kraków", "Polska")
    assert len(calls) == 1

    def fail(url, headers):
        raise AssertionError("should be served from the on-disk cache")

    reloaded = NominatimGeocoder(cache_path=tmp_path / "cache.json", min_interval=0, fetch=fail)
    assert reloaded.lookup(50.0612, 19.9371) == ("Kraków", "Polska")


def test_nominatim_caches_negative_results(tmp_path):
    geocoder, calls = make_nominatim(tmp_path, [{"error": "Unable to geocode"}])

    geocoder.lookup(40.0, -30.0)
    assert geocoder.lookup(40.0, -30.0) is None
    assert len(calls) == 1


def test_get_location_recognizer_builds_nominatim(tmp_path):
    from files_organizer.location_recognizers.geocoder import NominatimGeocoder

    recognizer = get_location_recognizer({"type": "nominatim", "cache_path": str(tmp_path / "c.json")})

    assert isinstance(recognizer.geocoder, NominatimGeocoder)
    assert recognizer.geocoder.cache_path == tmp_path / "c.json"


def test_nominatim_raises_when_offline_and_not_cached(tmp_path):
    import urllib.error

    from files_organizer.location_recognizers import GeocoderUnavailableError
    from files_organizer.location_recognizers.geocoder import NominatimGeocoder

    def offline(url, headers):
        raise urllib.error.URLError("no network")

    geocoder = NominatimGeocoder(cache_path=tmp_path / "cache.json", min_interval=0, fetch=offline)

    with pytest.raises(GeocoderUnavailableError):
        geocoder.lookup(48.21, 16.37)


def test_nominatim_serves_cached_name_when_offline(tmp_path):
    import urllib.error

    from files_organizer.location_recognizers.geocoder import NominatimGeocoder

    geocoder, _ = make_nominatim(tmp_path, [{"address": {"city": "Wiedeń", "country": "Austria"}}])
    geocoder.lookup(48.21, 16.37)

    def offline(url, headers):
        raise urllib.error.URLError("no network")

    reloaded = NominatimGeocoder(cache_path=tmp_path / "cache.json", min_interval=0, fetch=offline)
    assert reloaded.lookup(48.2101, 16.3701) == ("Wiedeń", "Austria")


def test_nominatim_cache_cell_size_is_configurable(tmp_path):
    from files_organizer.location_recognizers.geocoder import NominatimGeocoder

    calls = []

    def fetch(url, headers):
        calls.append(url)
        return {"address": {"city": "Kraków", "country": "Polska"}}

    geocoder = NominatimGeocoder(cache_path=tmp_path / "c.json", min_interval=0, cache_cell_km=10, fetch=fetch)
    row, col, lat, lon = geocoder._cache_cell(50.06, 19.94)
    geocoder.lookup(lat - 0.03, lon - 0.05)
    geocoder.lookup(lat + 0.03, lon + 0.05)  # ~7 km apart, both within the same 10 km cell

    assert len(calls) == 1


def test_nominatim_default_cells_are_about_two_km(tmp_path):
    from files_organizer.location_recognizers.geocoder import NominatimGeocoder

    geocoder = NominatimGeocoder(cache_path=tmp_path / "c.json")
    row, col, lat, lon = geocoder._cache_cell(54.35, 18.65)

    # cell centre +/- 0.9 km stays in the cell; 1.1 km off the centre leaves it (both axes)
    km_lat, km_lon = 1 / 111.32, 1 / (111.32 * math.cos(math.radians(lat)))
    assert geocoder._cache_cell(lat + 0.9 * km_lat, lon + 0.9 * km_lon)[:2] == (row, col)
    assert geocoder._cache_cell(lat - 0.9 * km_lat, lon - 0.9 * km_lon)[:2] == (row, col)
    assert geocoder._cache_cell(lat + 1.1 * km_lat, lon)[:2] != (row, col)
    assert geocoder._cache_cell(lat, lon + 1.1 * km_lon)[:2] != (row, col)
