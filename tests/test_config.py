from files_organizer.config import load_config


def test_load_config_parses_face_recognition_section(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
input_dir: "./data/input"
output_dir: "./data/output"
face_recognition:
  type: "deepface"
  known_faces_dir: "./known_faces"
  threshold: 0.35
"""
    )

    config = load_config(config_path)

    assert config.face_recognition == {
        "type": "deepface",
        "known_faces_dir": "./known_faces",
        "threshold": 0.35,
    }


def test_load_config_face_recognition_defaults_to_none(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text('input_dir: "./data/input"\noutput_dir: "./data/output"\n')

    config = load_config(config_path)

    assert config.face_recognition is None
