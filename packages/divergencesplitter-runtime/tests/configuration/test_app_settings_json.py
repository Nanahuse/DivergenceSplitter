import json
from pathlib import Path

import pytest
from divergencesplitter_runtime.configuration.app_settings_json import (
    default_app_settings,
    default_app_settings_path,
    load_app_settings,
    load_app_settings_or_default,
    save_app_settings,
)
from divergencesplitter_runtime.configuration.models import AppSettings
from divergencesplitter_runtime.configuration.strict_json import (
    ConfigurationFileError,
    ConfigurationValidationError,
)


def write_settings(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_default_app_settings_are_off_and_unselected() -> None:
    settings = default_app_settings()

    assert settings == AppSettings(1, "OFF", 0, None)


def test_round_trips_all_fields(tmp_path: Path) -> None:
    profile = str(tmp_path / "smw.json")
    settings = AppSettings(1, "DEBUG", 100, profile)
    path = tmp_path / "settings.json"

    save_app_settings(path, settings)

    assert load_app_settings(path) == settings


def test_round_trips_null_last_profile(tmp_path: Path) -> None:
    settings = AppSettings(1, "OFF", 0, None)
    path = tmp_path / "nested" / "settings.json"

    save_app_settings(path, settings)

    assert path.exists()
    assert load_app_settings(path) == settings
    assert load_app_settings(path).last_profile is None


@pytest.mark.parametrize(
    "value",
    [
        {"version": 1, "log_level": "OFF", "reaction_time_ms": 0, "unknown": 1},
        {"version": 1, "log_level": "OFF"},
        {"version": 2, "log_level": "OFF", "reaction_time_ms": 0},
        {"version": 1, "log_level": "TRACE", "reaction_time_ms": 0},
        {"version": 1, "log_level": "OFF", "reaction_time_ms": -1},
        {"version": 1, "log_level": "OFF", "reaction_time_ms": True},
        {"version": 1, "log_level": "OFF", "reaction_time_ms": "0"},
        {"version": 1, "log_level": "OFF", "reaction_time_ms": 1.5},
        {"version": 1, "log_level": "OFF", "reaction_time_ms": 0, "last_profile": 3},
        {"version": 1, "log_level": "OFF", "reaction_time_ms": 0, "last_profile": ""},
    ],
)
def test_rejects_invalid_schema(tmp_path: Path, value: object) -> None:
    path = tmp_path / "settings.json"
    write_settings(path, value)

    with pytest.raises(ConfigurationValidationError):
        load_app_settings(path)


def test_rejects_relative_last_profile(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    write_settings(
        path,
        {
            "version": 1,
            "log_level": "OFF",
            "reaction_time_ms": 0,
            "last_profile": "profiles/smw.json",
        },
    )

    with pytest.raises(ConfigurationValidationError):
        load_app_settings(path)


def test_rejects_duplicate_key(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        '{"version": 1, "log_level": "OFF", "log_level": "DEBUG", '
        '"reaction_time_ms": 0}',
        encoding="utf-8",
    )

    with pytest.raises(ConfigurationFileError):
        load_app_settings(path)


def test_missing_file_loads_defaults(tmp_path: Path) -> None:
    assert load_app_settings_or_default(tmp_path / "settings.json") == (
        default_app_settings()
    )


def test_invalid_file_loads_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    write_settings(
        path,
        {
            "version": 1,
            "log_level": "DEBUG",
            "reaction_time_ms": "broken",
            "last_profile": str(tmp_path / "profile.json"),
        },
    )

    settings = load_app_settings_or_default(path)

    assert settings == default_app_settings()
    assert settings.last_profile is None


def test_load_or_default_does_not_overwrite_invalid_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = '{"version": 1, "log_level": "DEBUG", "reaction_time_ms": "broken"}'
    path.write_text(original, encoding="utf-8")

    load_app_settings_or_default(path)

    assert path.read_text(encoding="utf-8") == original


def test_default_path_is_under_the_application_directory() -> None:
    path = default_app_settings_path()

    assert path.name == "settings.json"
    assert path.parent.name == "DivergenceSplitter"
