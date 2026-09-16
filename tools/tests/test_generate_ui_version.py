from __future__ import annotations

from pathlib import Path

import pytest
from generate_ui_version import generate_ui_version


def test_reads_version_from_project_metadata(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "_version.py"
    pyproject.write_text('[project]\nversion = "3.4.5"\n', encoding="utf-8")

    assert generate_ui_version(pyproject, output) == "3.4.5"


def test_generates_expected_version_module(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "src" / "divergencesplitter_ui" / "_version.py"
    pyproject.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    generate_ui_version(pyproject, output)

    expected = (
        '"""Generated application version. Do not edit manually."""\n\n'
        'VERSION = "1.2.3"\n'
    )
    assert output.read_text(encoding="utf-8") == expected


def test_generation_is_deterministic(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "_version.py"
    pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")

    generate_ui_version(pyproject, output)
    first = output.read_text(encoding="utf-8")
    generate_ui_version(pyproject, output)

    assert output.read_text(encoding="utf-8") == first


def test_missing_version_fails_without_creating_output(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "_version.py"
    pyproject.write_text('[project]\nname = "example"\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"\[project\]\.version"):
        generate_ui_version(pyproject, output)

    assert not output.exists()
