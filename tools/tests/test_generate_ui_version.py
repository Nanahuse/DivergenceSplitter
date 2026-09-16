from __future__ import annotations

from pathlib import Path

import pytest
from generate_ui_version import VERSION_MODULE, generate_ui_version


def write_ui_pyproject(ui_root: Path, version: str) -> None:
    (ui_root / "pyproject.toml").write_text(
        f'[project]\nversion = "{version}"\n', encoding="utf-8"
    )


def test_reads_version_from_ui_project_metadata(tmp_path: Path) -> None:
    write_ui_pyproject(tmp_path, "3.4.5")

    assert generate_ui_version(tmp_path) == "3.4.5"


def test_generates_expected_version_module(tmp_path: Path) -> None:
    write_ui_pyproject(tmp_path, "1.2.3")

    generate_ui_version(tmp_path)

    expected = (
        '"""Generated application version. Do not edit manually."""\n\n'
        'VERSION = "1.2.3"\n'
    )
    assert (tmp_path / VERSION_MODULE).read_text(encoding="utf-8") == expected


def test_generation_is_deterministic(tmp_path: Path) -> None:
    write_ui_pyproject(tmp_path, "0.1.0")

    generate_ui_version(tmp_path)
    first = (tmp_path / VERSION_MODULE).read_text(encoding="utf-8")
    generate_ui_version(tmp_path)

    assert (tmp_path / VERSION_MODULE).read_text(encoding="utf-8") == first


def test_missing_version_fails_without_creating_output(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "example"\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match=r"\[project\]\.version"):
        generate_ui_version(tmp_path)

    assert not (tmp_path / VERSION_MODULE).exists()
