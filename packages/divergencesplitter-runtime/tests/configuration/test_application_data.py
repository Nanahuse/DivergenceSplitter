import os
from pathlib import Path

from divergencesplitter_runtime.configuration.application_data import (
    _application_data_root,
    application_data_directory,
)


def test_windows_uses_appdata() -> None:
    result = _application_data_root("nt", {"APPDATA": r"C:\Users\Test\AppData\Roaming"})

    assert result == Path(r"C:\Users\Test\AppData\Roaming") / "DivergenceSplitter"


def test_windows_falls_back_to_home() -> None:
    result = _application_data_root("nt", {})

    assert result == Path.home() / "AppData" / "Roaming" / "DivergenceSplitter"


def test_other_platforms_use_xdg_config_home() -> None:
    result = _application_data_root("posix", {"XDG_CONFIG_HOME": "/tmp/xdg-config"})

    assert result == Path("/tmp/xdg-config") / "DivergenceSplitter"


def test_other_platforms_fall_back_to_home() -> None:
    result = _application_data_root("posix", {})

    assert result == Path.home() / ".config" / "DivergenceSplitter"


def test_application_data_directory_matches_the_host_platform() -> None:
    assert application_data_directory() == _application_data_root(os.name, os.environ)
