from __future__ import annotations

import functools
import gettext
import json
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
    here") is cached on disk under rounded coordinates - photos from one trip mostly
    hit the cache, and re-running over the same photos sends nothing again.

    The cache key is the coordinates rounded to `cache_precision` decimal places (2 = ~1 km,
    1 = ~10 km) - enough for a city-level name while letting nearby photos share one request.

    When the server can't be reached and the coordinates aren't cached, `lookup` raises
    `GeocoderUnavailableError` rather than returning None.
    """

    def __init__(
        self,
        language: str = "pl",
        cache_path: str | Path | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        min_interval: float = 1.0,
        cache_precision: int = 2,
        fetch: FetchFn | None = None,
    ):
        self.language = language
        self.cache_path = Path(cache_path or DEFAULT_NOMINATIM_CACHE).expanduser()
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.cache_precision = cache_precision
        self.fetch = fetch or _http_get_json
        self._cache: dict[str, list[str] | None] | None = None
        self._last_request = 0.0
        self._lock = threading.Lock()

    def lookup(self, latitude: float, longitude: float) -> tuple[str, str] | None:
        lat, lon = round(latitude, self.cache_precision), round(longitude, self.cache_precision)
        key = f"{self.language}:{lat:.{self.cache_precision}f},{lon:.{self.cache_precision}f}"
        with self._lock:
            cache = self._load_cache()
            if key in cache:
                cached = cache[key]
                return tuple(cached) if cached is not None else None

            # query the rounded point, so the cached name is the one for the whole cache cell
            found = self._request(lat, lon)
            cache[key] = list(found) if found is not None else None
            self._save_cache()
            return found

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

    def _load_cache(self) -> dict[str, list[str] | None]:
        if self._cache is None:
            try:
                self._cache = json.loads(self.cache_path.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                self._cache = {}
        return self._cache

    def _save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.cache_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(self._cache, ensure_ascii=False, indent=0))
        tmp_path.replace(self.cache_path)
