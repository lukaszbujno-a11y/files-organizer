from PIL import Image

from files_organizer.metadata import read_tagged_people, read_tags, write_tags


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
