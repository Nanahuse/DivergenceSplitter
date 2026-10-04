import sys
from pathlib import Path

import pytest
from divergencesplitter_runtime.configuration.application_data import (
    application_data_directory,
)
from divergencesplitter_ui.logs import log_file_path


def test_log_file_path_is_under_the_application_data_directory() -> None:
    assert log_file_path() == application_data_directory() / "diagnostics.log"


def test_log_file_path_ignores_cwd_and_executable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    expected = log_file_path()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "divergencesplitter.exe"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    assert log_file_path() == expected
