from __future__ import annotations

import functools
import gettext
import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable


class GeocoderUnavailableError(RuntimeError):
    """The geocoding service can't be reached (no internet, server error) and the answer isn't
    cached either. Unlike "nothing found at these coordinates", this must stop the whole run
    instead of quietly skipping the photo - otherwise a dropped connection would silently
    leave every remaining photo unplaced."""


class Geocoder(ABC):
    @abstractmethod
    def lookup(self, latitude: float, longitude: float) -> tuple[str, str] | None:
        """Return `(city, country)` for the given coordinates, or None if nothing was found.

        Raises `GeocoderUnavailableError` when the lookup itself couldn't be done.
        """
        ...


class ReverseGeocoderGeocoder(Geocoder):
    """Looks up the nearest city offline via the `reverse_geocoder` package, then maps its
    ISO 3166-1 country code to a full name via `pycountry`, translated to `language` (e.g. "pl"
    gives "Chorwacja" instead of "Croatia"; "en" keeps pycountry's English names).

    Only the country is translated - city names come straight from the GeoNames database
    behind `reverse_geocoder`, which stores them in ASCII English form ("Krakow", "Vienna").

    Both packages are imported lazily (only when `lookup` is actually called) so this module,
    and anything that imports it, doesn't require the `location_recognition` extra to be
    installed just to be loaded - matching how `InsightFaceDetector`/`InsightFaceEmbedder`
    defer their imports.
    """

    def __init__(self, language: str = "pl"):
        self.language = language

    def lookup(self, latitude: float, longitude: float) -> tuple[str, str] | None:
        import reverse_geocoder

        result = reverse_geocoder.search((latitude, longitude))[0]
        country = _country_name(result["cc"], self.language)
        if country is None:
            return None
        return result["name"], country


def _country_name(alpha_2: str, language: str = "en") -> str | None:
    import pycountry

    country = pycountry.countries.get(alpha_2=alpha_2)
    if country is None:
        return None
    if language == "en":
        return country.name
    return _translation(language).gettext(country.name)


@functools.cache
def _translation(language: str) -> gettext.NullTranslations:
    import pycountry

    # fallback: an unknown language code keeps the English names instead of failing every lookup
    return gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=[language], fallback=True)


NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
DEFAULT_USER_AGENT = "files-organizer/0.1 (+https://github.com/lukaszbujno-a11y/files-organizer)"
DEFAULT_NOMINATIM_CACHE = Path("~/.cache/files-organizer/nominatim.json")

# Most specific settlement level first; `municipality` comes last since for some countries
# (e.g. Ukraine) it's an administrative unit name OSM only has in the local language.
_PLACE_KEYS = ("city", "town", "village", "hamlet", "municipality", "county")

_KM_PER_DEGREE = 111.32  # length of one degree of latitude
_EARTH_RADIUS_KM = 6371.0

FetchFn = Callable[[str, dict[str, str]], dict]


def _http_get_json(url: str, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


class NominatimGeocoder(Geocoder):
    """Looks up city/country online via OpenStreetMap's Nominatim reverse-geocoding API, with
    names in `language` - unlike `ReverseGeocoderGeocoder` this gives localized city names with
    diacritics ("Kraków", "Wiedeń", "Lwów"), not just localized countries.

    This sends the photo's GPS coordinates (never the photo itself) to nominatim.openstreetmap.org.
    The public server's usage policy allows at most 1 request per second and requires an
    identifying User-Agent, so requests are throttled, and every result (including "nothing
    here") is cached on disk - photos from one trip mostly hit the cache, and re-running over
    the same photos sends nothing again.

    A lookup is answered from the cache when an already-resolved point lies within
    `cache_radius_km` of it (the nearest such point wins) - enough for a city-level name while
    letting nearby photos share one request, without the edge effects of a fixed grid where two
    photos a few metres apart can still land in different cells.

    When the server can't be reached and nothing cached is close enough, `lookup` raises
    `GeocoderUnavailableError` rather than returning None.
    """

    def __init__(
        self,
        language: str = "pl",
        cache_path: str | Path | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval: float = 1.0,
        cache_radius_km: float = 2.0,
        fetch: FetchFn | None = None,
    ):
        self.language = language
        self.cache_path = Path(cache_path or DEFAULT_NOMINATIM_CACHE).expanduser()
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.cache_radius_km = cache_radius_km
        self.fetch = fetch or _http_get_json
        self._cache: list[dict] | None = None
        self._last_request = 0.0
        self._lock = threading.Lock()

    def lookup(self, latitude: float, longitude: float) -> tuple[str, str] | None:
        with self._lock:
            cached = self._nearest_cached(latitude, longitude)
            if cached is not None:
                return (cached["city"], cached["country"]) if cached["city"] is not None else None

            found = self._request(latitude, longitude)
            city, country = found if found is not None else (None, None)
            self._load_cache().append(
                {"lat": latitude, "lon": longitude, "language": self.language, "city": city, "country": country}
            )
            self._save_cache()
            return found

    def _nearest_cached(self, latitude: float, longitude: float) -> dict | None:
        # cheap latitude pre-filter before the exact distance - a linear scan is fine for the
        # few thousand distinct places a photo library realistically has
        max_lat_delta = self.cache_radius_km / _KM_PER_DEGREE
        best, best_km = None, self.cache_radius_km
        for entry in self._load_cache():
            if entry["language"] != self.language or abs(entry["lat"] - latitude) > max_lat_delta:
                continue
            km = _distance_km(latitude, longitude, entry["lat"], entry["lon"])
            if km <= best_km:
                best, best_km = entry, km
        return best

    def _request(self, latitude: float, longitude: float) -> tuple[str, str] | None:
        wait = self.min_interval - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        query = urllib.parse.urlencode(
            {"lat": latitude, "lon": longitude, "format": "jsonv2", "zoom": 12, "accept-language": self.language}
        )
        try:
            data = self.fetch(f"{NOMINATIM_URL}?{query}", {"User-Agent": self.user_agent})
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise GeocoderUnavailableError(
                f"Brak połączenia z {NOMINATIM_URL} i brak nazwy w cache dla ({latitude}, {longitude}): {exc}"
            ) from exc
        finally:
            self._last_request = time.monotonic()

        address = data.get("address") or {}
        city = next((address[key] for key in _PLACE_KEYS if address.get(key)), None)
        country = address.get("country")
        if city is None or country is None:
            return None
        return city, country

    def _load_cache(self) -> list[dict]:
        if self._cache is None:
            try:
                data = json.loads(self.cache_path.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                data = None
            # anything else (e.g. the earlier grid-keyed dict format) is just discarded
            self._cache = data.get("entries", []) if isinstance(data, dict) and data.get("version") == 2 else []
        return self._cache

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.cache_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps({"version": 2, "entries": self._cache}, ensure_ascii=False, indent=0))
        tmp_path.replace(self.cache_path)


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle (haversine) distance between two points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi, d_lambda = phi2 - phi1, math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))
