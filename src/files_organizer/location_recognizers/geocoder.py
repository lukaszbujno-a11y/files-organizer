from __future__ import annotations

from abc import ABC, abstractmethod


class Geocoder(ABC):
    @abstractmethod
    def lookup(self, latitude: float, longitude: float) -> tuple[str, str] | None:
        """Return `(city, country)` for the given coordinates, or None if nothing was found."""
        ...


class ReverseGeocoderGeocoder(Geocoder):
    """Looks up the nearest city offline via the `reverse_geocoder` package, then maps its
    ISO 3166-1 country code to a full name via `pycountry`.

    Both packages are imported lazily (only when `lookup` is actually called) so this module,
    and anything that imports it, doesn't require the `location_recognition` extra to be
    installed just to be loaded - matching how `InsightFaceDetector`/`InsightFaceEmbedder`
    defer their imports.
    """

    def lookup(self, latitude: float, longitude: float) -> tuple[str, str] | None:
        import reverse_geocoder

        result = reverse_geocoder.search((latitude, longitude))[0]
        country = _country_name(result["cc"])
        if country is None:
            return None
        return result["name"], country


def _country_name(alpha_2: str) -> str | None:
    import pycountry

    country = pycountry.countries.get(alpha_2=alpha_2)
    return country.name if country else None
