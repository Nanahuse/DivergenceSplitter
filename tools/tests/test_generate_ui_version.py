from __future__ import annotations

from pathlib import Path

import pytest
from generate_ui_version import generate_ui_version


def test_generates_deterministic_version_module(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "src" / "divergencesplitter_ui" / "_version.py"
    pyproject.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")

    assert generate_ui_version(pyproject, output) == "1.2.3"
    expected = (
        '"""Generated application version. Do not edit manually."""\n\n'
        'VERSION = "1.2.3"\n'
    )
    assert output.read_text(encoding="utf-8") == expected
    assert generate_ui_version(pyproject, output) == "1.2.3"
    assert output.read_text(encoding="utf-8") == expected


def test_missing_version_fails_without_creating_output(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    output = tmp_path / "_version.py"
    pyproject.write_text('[project]\nname = "example"\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"\[project\]\.version"):
        generate_ui_version(pyproject, output)

    assert not output.exists()
