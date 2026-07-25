from files_organizer.calendar_sources.google_source import _extract_tag


def test_extract_tag_from_title():
    assert _extract_tag({"summary": "#Wakacje Wyjazd nad morze"}) == "Wakacje"


def test_extract_tag_from_description_when_missing_in_title():
    item = {"summary": "Wyjazd nad morze", "description": "notatki #Rodzina tutaj"}
    assert _extract_tag(item) == "Rodzina"


def test_extract_tag_missing_returns_none():
    assert _extract_tag({"summary": "Spotkanie", "description": "bez tagu"}) is None


def test_extract_tag_title_takes_priority_over_description():
    item = {"summary": "#Wakacje", "description": "#Rodzina"}
    assert _extract_tag(item) == "Wakacje"
