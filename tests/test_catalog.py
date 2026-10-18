import os
import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest
from PIL import Image

from files_organizer import catalog as catalog_module
from files_organizer.catalog import Catalog, CatalogQuery, open_catalog
from files_organizer.config import Config
from files_organizer.models import RecognizedLocation


def make_jpeg(path: Path, *exiftool_args: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2)).save(path, "JPEG")
    if exiftool_args:
        subprocess.run(["exiftool", "-overwrite_original", *exiftool_args, str(path)], capture_output=True, check=True)
    return path


@pytest.fixture
def catalog(tmp_path):
    with Catalog(tmp_path / "catalog.sqlite") as opened:
        yield opened


def test_scan_stores_date_phone_gps_and_tags(tmp_path, catalog):
    photo = make_jpeg(
        tmp_path / "in" / "a.jpg",
        "-DateTimeOriginal=2026:07:15 12:30:00",
        "-Make=Apple",
        "-Model=iPhone 15 Pro",
        "-GPSLatitude=43.5",
        "-GPSLatitudeRef=N",
        "-GPSLongitude=16.4",
        "-GPSLongitudeRef=E",
        "-Keywords=Person:Anna",
        "-Keywords=Country:Chorwacja",
        "-Keywords=wakacje",
    )

    result = catalog.scan(tmp_path / "in")

    assert (result.added, result.updated, result.unchanged) == (1, 0, 0)
    entry = catalog.get(photo)
    assert entry.taken_at == datetime(2026, 7, 15, 12, 30)
    assert entry.date_source == "exif"
    assert (entry.make, entry.model) == ("Apple", "iPhone 15 Pro")
    assert entry.gps == pytest.approx((43.5, 16.4))
    assert entry.media_type == "image"
    assert set(entry.tags) == {("person", "Anna"), ("country", "Chorwacja"), ("keyword", "wakacje")}


def test_file_without_exif_date_falls_back_to_mtime(tmp_path, catalog):
    photo = make_jpeg(tmp_path / "in" / "plain.jpg")

    catalog.scan(tmp_path / "in")

    entry = catalog.get(photo)
    assert entry.date_source == "mtime"
    assert entry.taken_at == datetime.fromtimestamp(photo.stat().st_mtime)
    assert entry.model is None and entry.gps is None


def test_rescan_reads_only_new_and_changed_files(tmp_path, catalog, monkeypatch):
    first = make_jpeg(tmp_path / "in" / "a.jpg")
    make_jpeg(tmp_path / "in" / "b.jpg")
    catalog.scan(tmp_path / "in")

    make_jpeg(tmp_path / "in" / "c.jpg")
    os.utime(first, ns=(first.stat().st_atime_ns, first.stat().st_mtime_ns + 1_000_000_000))
    read = []
    original = catalog_module.read_metadata_batch
    monkeypatch.setattr(catalog_module, "read_metadata_batch", lambda paths: read.extend(paths) or original(paths))

    result = catalog.scan(tmp_path / "in")

    assert sorted(path.name for path in read) == ["a.jpg", "c.jpg"]
    assert (result.added, result.updated, result.unchanged, result.removed) == (1, 1, 1, 0)


def test_rescan_removes_deleted_files_only_under_the_scanned_root(tmp_path, catalog):
    gone = make_jpeg(tmp_path / "in" / "gone.jpg")
    other = make_jpeg(tmp_path / "in_other" / "keep.jpg")
    catalog.scan(tmp_path / "in")
    catalog.scan(tmp_path / "in_other")

    gone.unlink()
    result = catalog.scan(tmp_path / "in")

    assert result.removed == 1
    assert catalog.count(CatalogQuery()) == 1
    assert catalog.get(other) is not None


def test_scan_in_batches(tmp_path, catalog):
    for i in range(5):
        make_jpeg(tmp_path / "in" / f"{i}.jpg", f"-DateTimeOriginal=2026:07:1{i} 10:00:00")
    lines = []

    catalog.scan(tmp_path / "in", log=lines.append, batch_size=2)

    assert [entry.taken_at.day for entry in catalog.search(CatalogQuery())] == [10, 11, 12, 13, 14]
    assert sum("odczytano" in line for line in lines) == 3


def test_stopped_scan_keeps_finished_batches_and_removes_nothing(tmp_path, catalog):
    for i in range(4):
        make_jpeg(tmp_path / "in" / f"{i}.jpg")
    batches = []

    result = catalog.scan(tmp_path / "in", log=batches.append, should_stop=lambda: len(batches) >= 2, batch_size=2)

    assert result.stopped
    assert catalog.count(CatalogQuery()) == 2


def test_get_returns_none_once_the_file_changed(tmp_path, catalog):
    photo = make_jpeg(tmp_path / "in" / "a.jpg")
    catalog.scan(tmp_path / "in")

    photo.write_bytes(photo.read_bytes() + b"x")

    assert catalog.get(photo) is None
    assert catalog.refresh(photo).size == photo.stat().st_size


def test_rescan_of_a_changed_file_forgets_its_resolved_location(tmp_path, catalog):
    photo = make_jpeg(tmp_path / "in" / "a.jpg")
    catalog.scan(tmp_path / "in")
    catalog.set_location(photo, RecognizedLocation("Split", "Chorwacja", 43.5, 16.4), "nominatim:pl")
    assert catalog.get(photo).city == "Split"

    photo.write_bytes(photo.read_bytes() + b"x")
    catalog.scan(tmp_path / "in")

    assert catalog.get(photo).city is None


def test_record_placed_follows_moves_and_copies(tmp_path, catalog):
    moved = make_jpeg(tmp_path / "in" / "moved.jpg", "-Model=Pixel 8", "-Keywords=Person:Ola")
    copied = make_jpeg(tmp_path / "in" / "copied.jpg", "-Model=Pixel 8", "-Keywords=Person:Ola")
    catalog.scan(tmp_path / "in")

    out = tmp_path / "out"
    out.mkdir()
    moved_to = out / moved.name
    moved.rename(moved_to)
    catalog.record_placed(moved, moved_to, moved=True)
    copied_to = out / copied.name
    copied_to.write_bytes(copied.read_bytes())
    catalog.record_placed(copied, copied_to, moved=False)

    assert catalog.get(moved) is None
    assert catalog.get(moved_to).model == "Pixel 8"
    assert catalog.get(copied).model == "Pixel 8"
    assert catalog.get(copied_to).tags == (("person", "Ola"),)


def test_search_filters(tmp_path, catalog):
    make_jpeg(tmp_path / "in" / "a.jpg", "-DateTimeOriginal=2026:07:15 10:00:00", "-Model=iPhone 15 Pro", "-Keywords=Person:Anna")
    make_jpeg(tmp_path / "in" / "b.jpg", "-DateTimeOriginal=2026:07:16 23:59:00", "-Model=Pixel 8", "-GPSLatitude=1", "-GPSLongitude=1")
    make_jpeg(tmp_path / "in" / "c.jpg", "-Keywords=Country:Chorwacja")
    catalog.scan(tmp_path / "in")
    names = lambda **query: [entry.path.name for entry in catalog.search(CatalogQuery(**query))]

    assert names(taken_from=date(2026, 7, 16), taken_to=date(2026, 7, 16)) == ["b.jpg"]
    assert names(model="iPhone 15 Pro") == ["a.jpg"]
    assert names(person="anna") == ["a.jpg"]
    assert names(country="chorwacja") == ["c.jpg"]
    assert names(without_exif_date=True) == ["c.jpg"]
    assert sorted(names(without_gps=True)) == ["a.jpg", "c.jpg"]
    assert names(limit=1) == ["a.jpg"]
    assert catalog.count(CatalogQuery(without_gps=True)) == 2
    assert catalog.facets() == {"models": ["Pixel 8", "iPhone 15 Pro"], "countries": ["Chorwacja"], "people": ["Anna"]}


def test_country_search_also_matches_the_location_rule_result(tmp_path, catalog):
    photo = make_jpeg(tmp_path / "in" / "a.jpg")
    catalog.scan(tmp_path / "in")
    catalog.set_location(photo, RecognizedLocation("Split", "Chorwacja", 43.5, 16.4), "nominatim:pl")

    assert [entry.path for entry in catalog.search(CatalogQuery(country="Chorwacja"))] == [Path(os.path.abspath(photo))]


def test_outdated_schema_is_rebuilt(tmp_path):
    db_path = tmp_path / "catalog.sqlite"
    with Catalog(db_path) as opened:
        opened._db.execute("PRAGMA user_version = 0")
        opened._db.commit()

    with Catalog(db_path) as reopened:
        assert reopened.count(CatalogQuery()) == 0


def test_open_catalog_respects_config(tmp_path):
    config = Config(input_dir=tmp_path, output_dir=None, catalog={"path": str(tmp_path / "c.sqlite")})
    with open_catalog(config) as opened:
        assert opened.path == tmp_path / "c.sqlite"
    assert open_catalog(Config(input_dir=tmp_path, output_dir=None, catalog={"enabled": False})) is None
