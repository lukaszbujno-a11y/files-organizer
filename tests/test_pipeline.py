from datetime import datetime
from pathlib import Path

import pytest

from files_organizer import pipeline
from files_organizer.config import Config
from files_organizer.models import Photo


def run_with_photos(monkeypatch, tmp_path, photos: list[Photo], dry_run: bool, **config_overrides) -> list[str]:
    by_path = {photo.path: photo for photo in photos}
    monkeypatch.setattr(pipeline, "iter_media_files", lambda input_dir: list(by_path))
    monkeypatch.setattr(pipeline, "read_photo_metadata", lambda path: by_path[path])
    config = Config(input_dir=tmp_path / "input", output_dir=tmp_path / "output", **config_overrides)
    lines: list[str] = []
    pipeline.run_pipeline(config, dry_run=dry_run, log=lines.append)
    return lines


def make_photos(tmp_path: Path, day: datetime, count: int) -> list[Photo]:
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)
    photos = []
    for i in range(count):
        path = input_dir / f"{day:%Y%m%d}_{i}.jpg"
        path.write_bytes(b"jpeg")
        photos.append(Photo(path=path, taken_at=day.replace(hour=12, minute=i)))
    return photos


def test_date_rule_copies_big_days_and_skips_small_ones(monkeypatch, tmp_path):
    photos = make_photos(tmp_path, datetime(2026, 7, 15), 6) + make_photos(tmp_path, datetime(2026, 7, 16), 2)

    run_with_photos(monkeypatch, tmp_path, photos, dry_run=False, rules=("calendar", "date"))

    day_dir = tmp_path / "output" / "2026" / "07" / "2026-07-15"
    assert sorted(p.name for p in day_dir.iterdir()) == sorted(p.path.name for p in photos[:6])
    assert not (tmp_path / "output" / "2026" / "07" / "2026-07-16").exists()


def test_dry_run_does_not_touch_output(monkeypatch, tmp_path):
    photos = make_photos(tmp_path, datetime(2026, 7, 15), 6)

    lines = run_with_photos(monkeypatch, tmp_path, photos, dry_run=True, rules=("date",))

    assert not (tmp_path / "output").exists()
    assert any(line.endswith("-> 2026/07/2026-07-15 [data: 6 zdjęć z dnia]") for line in lines)


def test_log_explains_why_a_photo_was_skipped(monkeypatch, tmp_path):
    photos = make_photos(tmp_path, datetime(2026, 7, 15), 3)

    lines = run_with_photos(monkeypatch, tmp_path, photos, dry_run=True, rules=("calendar", "date"))

    skipped = [line for line in lines if "pominięto" in line]
    assert len(skipped) == 3
    assert "kalendarz: brak wydarzenia; data: 3 zdjęć z dnia, potrzeba > 5" in skipped[0]
    assert any(line.startswith("[2/3] Analiza zakończona") and "pominięte: 3" in line for line in lines)


def test_without_date_rule_each_file_is_placed_before_the_next_is_read(monkeypatch, tmp_path):
    photos = make_photos(tmp_path, datetime(2026, 7, 15), 2)
    by_path = {photo.path: photo for photo in photos}
    lines: list[str] = []

    def read(path):
        lines.append(f"read {path.name}")
        return by_path[path]

    monkeypatch.setattr(pipeline, "iter_media_files", lambda input_dir: list(by_path))
    monkeypatch.setattr(pipeline, "read_photo_metadata", read)
    config = Config(input_dir=tmp_path / "input", output_dir=tmp_path / "output", rules=("calendar",))

    pipeline.run_pipeline(config, dry_run=True, log=lines.append)

    events = [line for line in lines if line.startswith("read ") or "-> pominięto" in line]
    assert events == [
        "read 20260715_0.jpg",
        "[1/2] 20260715_0.jpg (2026-07-15 12:00) -> pominięto (kalendarz: brak wydarzenia)",
        "read 20260715_1.jpg",
        "[2/2] 20260715_1.jpg (2026-07-15 12:01) -> pominięto (kalendarz: brak wydarzenia)",
    ]


def make_exif_photo(path: Path, *exiftool_args: str) -> Path:
    import subprocess

    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2)).save(path, "JPEG")
    subprocess.run(["exiftool", "-overwrite_original", *exiftool_args, str(path)], capture_output=True, check=True)
    return path


def test_with_catalog_a_rerun_reads_no_file_with_exiftool(monkeypatch, tmp_path):
    from files_organizer import catalog as catalog_module
    from files_organizer.catalog import Catalog

    for i in range(6):
        make_exif_photo(tmp_path / "input" / f"{i}.jpg", f"-DateTimeOriginal=2026:07:15 12:0{i}:00", "-Model=Pixel 8")
    config = Config(input_dir=tmp_path / "input", output_dir=tmp_path / "output", rules=("date",))
    read_batches = []
    original = catalog_module.read_metadata_batch
    monkeypatch.setattr(catalog_module, "read_metadata_batch", lambda paths: read_batches.append(len(paths)) or original(paths))
    monkeypatch.setattr(pipeline, "read_photo_metadata", lambda path: pytest.fail("read past the catalog"))

    with Catalog(tmp_path / "catalog.sqlite") as catalog:
        pipeline.run_pipeline(config, dry_run=True, log=lambda line: None, catalog=catalog)
        lines: list[str] = []
        pipeline.run_pipeline(config, dry_run=True, log=lines.append, catalog=catalog)

    assert read_batches == [6]
    assert "[2/4] Katalog: nowe: 0, zmienione: 0, usunięte: 0, bez zmian: 6" in " ".join(lines)
    assert any(line.endswith("-> 2026/07/2026-07-15 [data: 6 zdjęć z dnia]") for line in lines)


def test_with_catalog_moved_files_keep_their_entries(tmp_path):
    from files_organizer.catalog import Catalog

    photo = make_exif_photo(tmp_path / "input" / "a.jpg", "-DateTimeOriginal=2026:07:15 12:00:00", "-Model=Pixel 8")
    config = Config(input_dir=tmp_path / "input", output_dir=tmp_path / "output", rules=("date",), date_group_threshold=0, mode="move")

    with Catalog(tmp_path / "catalog.sqlite") as catalog:
        pipeline.run_pipeline(config, dry_run=False, log=lambda line: None, catalog=catalog)

        moved_to = tmp_path / "output" / "2026" / "07" / "2026-07-15" / "a.jpg"
        assert not photo.exists() and moved_to.exists()
        assert catalog.get(moved_to).model == "Pixel 8"
        assert catalog.get(photo) is None


def test_with_catalog_resolved_places_are_not_looked_up_again(monkeypatch, tmp_path):
    from files_organizer.catalog import Catalog
    from files_organizer.location_recognizers import LocationRecognizer
    from files_organizer.models import RecognizedLocation

    make_exif_photo(
        tmp_path / "input" / "a.jpg",
        "-DateTimeOriginal=2026:07:15 12:00:00",
        "-GPSLatitude=43.5",
        "-GPSLatitudeRef=N",
        "-GPSLongitude=16.4",
        "-GPSLongitudeRef=E",
    )
    lookups = []

    class FakeRecognizer(LocationRecognizer):
        def __init__(self, gps_reader):
            self.gps_reader = gps_reader

        def recognize(self, path):
            latitude, longitude = self.gps_reader(path)
            lookups.append(path.name)
            self.last_source = "api"
            return RecognizedLocation("Split", "Chorwacja", latitude, longitude)

    monkeypatch.setattr(pipeline, "get_location_recognizer", lambda config, gps_reader=None: FakeRecognizer(gps_reader))
    config = Config(input_dir=tmp_path / "input", output_dir=tmp_path / "output", rules=("location",))

    with Catalog(tmp_path / "catalog.sqlite") as catalog:
        pipeline.run_pipeline(config, dry_run=True, log=lambda line: None, catalog=catalog)
        lines: list[str] = []
        pipeline.run_pipeline(config, dry_run=True, log=lines.append, catalog=catalog)

    assert lookups == ["a.jpg"]
    assert any("2026-07-15 Chorwacja-Split [lokalizacja: Split, Chorwacja]" in line for line in lines)
    assert any("[katalog]" in line for line in lines)
