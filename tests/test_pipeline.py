from datetime import datetime
from pathlib import Path

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
