from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..exif_reader import read_gps
from ..models import RecognizedLocation
from .base import LocationRecognizer
from .geocoder import Geocoder, ReverseGeocoderGeocoder

GpsReader = Callable[[Path], "tuple[float, float] | None"]


class ReverseGeocoderRecognizer(LocationRecognizer):
    """Default LocationRecognizer: GPS from EXIF, resolved to a city/country via a Geocoder.

    Unlike face recognition there's no enrollment step - `reverse_geocoder`'s city database
    is generic, not built from user-provided reference photos - so this is a single class
    rather than a detector/embedder/index pipeline.
    """

    def __init__(self, geocoder: Geocoder | None = None, gps_reader: GpsReader | None = None):
        self.geocoder = geocoder or ReverseGeocoderGeocoder()
        self.gps_reader = gps_reader or read_gps

    def recognize(self, path: Path) -> RecognizedLocation | None:
        coords = self.gps_reader(path)
        if coords is None:
            return None
        latitude, longitude = coords

        found = self.geocoder.lookup(latitude, longitude)
        if found is None:
            return None
        city, country = found
        return RecognizedLocation(city=city, country=country, latitude=latitude, longitude=longitude)
