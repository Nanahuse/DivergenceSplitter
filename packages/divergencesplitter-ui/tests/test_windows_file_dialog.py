from pathlib import Path

from divergencesplitter_ui.windows_file_dialog import (
    CONFIGURATION_FILTERS,
    SCENARIO_FILTERS,
    VIDEO_FILTERS,
    filter_string,
    normalize_selected_path,
)


def test_configuration_filter_contains_json_and_all_files() -> None:
    value = filter_string(CONFIGURATION_FILTERS)
    assert "JSON configuration\0*.json" in value
    assert "All files\0*.*" in value


def test_scenario_filter_contains_supported_extensions() -> None:
    value = filter_string(SCENARIO_FILTERS)
    assert "Scenario files\0*.py;*.yaml;*.yml" in value


def test_video_filter_contains_supported_extensions() -> None:
    value = filter_string(VIDEO_FILTERS)
    assert "Video files\0*.mp4;*.mkv;*.avi;*.mov;*.webm;*.m4v" in value


def test_cancel_is_none_and_selected_path_is_absolute() -> None:
    assert normalize_selected_path(None) is None
    selected = normalize_selected_path("config.json")
    assert selected is not None
    assert selected == Path("config.json").resolve()
