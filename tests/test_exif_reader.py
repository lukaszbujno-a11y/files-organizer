from pathlib import Path

from PIL import Image

from files_organizer.exif_reader import iter_media_files, read_photo_metadata


def test_iter_media_files_filters_by_supported_suffix(tmp_path):
    (tmp_path / "photo.jpg").write_bytes(b"fake")
    (tmp_path / "video.mp4").write_bytes(b"fake")
    (tmp_path / "notes.txt").write_text("ignore me")

    found = {path.name for path in iter_media_files(tmp_path)}

    assert found == {"photo.jpg", "video.mp4"}


def test_read_photo_metadata_falls_back_to_mtime_without_exif(tmp_path):
    path = tmp_path / "plain.jpg"
    Image.new("RGB", (2, 2)).save(path, "JPEG")

    photo = read_photo_metadata(path)

    assert photo.path == path
    assert photo.taken_at is not None
    assert photo.camera_model is None
