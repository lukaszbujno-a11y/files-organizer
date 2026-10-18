from __future__ import annotations

import functools
import gettext
from abc import ABC, abstractmethod


class Geocoder(ABC):
    @abstractmethod
    def lookup(self, latitude: float, longitude: float) -> tuple[str, str] | None:
        """Return `(city, country)` for the given coordinates, or None if nothing was found."""
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
