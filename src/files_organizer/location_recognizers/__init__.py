from .base import LocationRecognizer
from .geocoder import DEFAULT_USER_AGENT, NominatimGeocoder, ReverseGeocoderGeocoder
from .reverse_geocoder_recognizer import ReverseGeocoderRecognizer

__all__ = ["LocationRecognizer", "ReverseGeocoderRecognizer", "get_location_recognizer"]


def get_location_recognizer(config: dict) -> LocationRecognizer:
    recognizer_type = config.get("type", "reverse_geocoder")

    if recognizer_type == "reverse_geocoder":
        return ReverseGeocoderRecognizer(geocoder=ReverseGeocoderGeocoder(language=config.get("language", "pl")))

    if recognizer_type == "nominatim":
        geocoder = NominatimGeocoder(
            language=config.get("language", "pl"),
            cache_path=config.get("cache_path"),
            user_agent=config.get("user_agent", DEFAULT_USER_AGENT),
        )
        return ReverseGeocoderRecognizer(geocoder=geocoder)

    raise ValueError(f"Unknown location_recognition type: {recognizer_type!r}")
