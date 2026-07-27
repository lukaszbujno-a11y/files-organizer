import subprocess

from PIL import Image

from files_organizer.metadata import (
    read_tagged_countries,
    read_tagged_locations,
    read_tagged_people,
    read_tags,
    remove_location_tags,
    remove_person_tags,
    write_location_tags,
    write_tags,
)
from files_organizer.models import RecognizedLocation


def _make_jpeg(path):
    Image.new("RGB", (2, 2)).save(path, "JPEG")


def test_read_tags_empty_for_untagged_file(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)

    assert read_tags(path) == []


def test_write_tags_adds_person_keyword(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)

    write_tags(path, ["Anna"])

    assert read_tagged_people(path) == ["Anna"]


def test_write_tags_accumulates_multiple_people(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)

    write_tags(path, ["Anna"])
    write_tags(path, ["Bartek"])

    assert set(read_tagged_people(path)) == {"Anna", "Bartek"}


def test_write_tags_is_idempotent(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)

    write_tags(path, ["Anna"])
    write_tags(path, ["Anna"])

    assert read_tags(path) == ["Person:Anna"]


def test_remove_person_tags_removes_all_and_returns_names(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)

    write_tags(path, ["Anna", "Bartek"])
    removed = remove_person_tags(path)

    assert set(removed) == {"Anna", "Bartek"}
    assert read_tagged_people(path) == []


def test_remove_person_tags_leaves_other_keywords(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)

    write_tags(path, ["Anna"])
    subprocess.run(
        ["exiftool", "-overwrite_original", "-Keywords+=Wakacje", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )

    remove_person_tags(path)

    assert read_tags(path) == ["Wakacje"]


def test_remove_person_tags_is_noop_when_no_person_tags(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)

    assert remove_person_tags(path) == []


def test_write_location_tags_adds_location_and_country_keywords(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)

    write_location_tags(path, RecognizedLocation(city="Zakopane", country="Poland", latitude=49.3, longitude=19.9))

    assert read_tagged_locations(path) == ["Zakopane"]
    assert read_tagged_countries(path) == ["Poland"]


def test_write_location_tags_is_idempotent(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)
    location = RecognizedLocation(city="Zakopane", country="Poland", latitude=49.3, longitude=19.9)

    write_location_tags(path, location)
    write_location_tags(path, location)

    assert read_tags(path) == ["Location:Zakopane", "Country:Poland"]


def test_remove_location_tags_removes_all_and_returns_values(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)
    write_location_tags(path, RecognizedLocation(city="Zakopane", country="Poland", latitude=49.3, longitude=19.9))

    removed = remove_location_tags(path)

    assert set(removed) == {"Zakopane", "Poland"}
    assert read_tagged_locations(path) == []
    assert read_tagged_countries(path) == []


def test_remove_location_tags_leaves_other_keywords(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)
    write_location_tags(path, RecognizedLocation(city="Zakopane", country="Poland", latitude=49.3, longitude=19.9))
    write_tags(path, ["Anna"])

    remove_location_tags(path)

    assert read_tags(path) == ["Person:Anna"]


def test_remove_location_tags_is_noop_when_no_location_tags(tmp_path):
    path = tmp_path / "photo.jpg"
    _make_jpeg(path)

    assert remove_location_tags(path) == []
