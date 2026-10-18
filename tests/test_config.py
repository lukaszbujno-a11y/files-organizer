import pytest

from files_organizer.config import Config, load_config, with_rule_enabled


def test_load_config_parses_face_recognition_section(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
input_dir: "./data/input"
output_dir: "./data/output"
face_recognition:
  type: "insightface"
  known_faces_dir: "./known_faces"
  threshold: 0.35
"""
    )

    config = load_config(config_path)

    assert config.face_recognition == {
        "type": "insightface",
        "known_faces_dir": "./known_faces",
        "threshold": 0.35,
    }


def test_load_config_face_recognition_defaults_to_none(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text('input_dir: "./data/input"\noutput_dir: "./data/output"\n')

    config = load_config(config_path)

    assert config.face_recognition is None


def test_load_config_parses_location_recognition_section(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
input_dir: "./data/input"
output_dir: "./data/output"
location_recognition:
  type: "reverse_geocoder"
"""
    )

    config = load_config(config_path)

    assert config.location_recognition == {"type": "reverse_geocoder"}


def test_load_config_location_recognition_defaults_to_none(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text('input_dir: "./data/input"\noutput_dir: "./data/output"\n')

    config = load_config(config_path)

    assert config.location_recognition is None


def test_load_config_rules_default_to_calendar_only(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text('input_dir: "./data/input"\noutput_dir: "./data/output"\n')

    config = load_config(config_path)

    assert config.rules == ("calendar",)
    assert config.date_group_threshold == 5
    assert config.home_country is None


def test_load_config_parses_rules_order(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
input_dir: "./data/input"
output_dir: "./data/output"
rules: ["date", "calendar"]
home_country: "Poland"
date_group_threshold: 10
"""
    )

    config = load_config(config_path)

    assert config.rules == ("date", "calendar")
    assert config.home_country == "Poland"
    assert config.date_group_threshold == 10


def test_unknown_rule_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unknown rules"):
        Config(input_dir=tmp_path, output_dir=tmp_path, rules=("calendar", "weather"))


def test_with_rule_enabled_keeps_custom_order_and_inserts_by_default_order():
    assert with_rule_enabled(("date", "calendar"), "location", False) == ("date", "calendar")
    assert with_rule_enabled(("calendar", "date"), "location", True) == ("calendar", "location", "date")
    assert with_rule_enabled(("date", "calendar"), "date", False) == ("calendar",)
    assert with_rule_enabled(("calendar",), "date", True) == ("calendar", "date")
