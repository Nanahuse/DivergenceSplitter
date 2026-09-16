from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from prepare_flet_build_experiment import (
    DEV_PACKAGES,
    WINDOWS_DEPENDENCIES,
    add_windows_dependencies,
    prepare_metadata,
)


@pytest.mark.parametrize(
    "initial", ["dependencies = []", 'dependencies = [\n    "existing>=1",\n]']
)
def test_add_windows_dependencies_handles_empty_and_multiline(initial: str) -> None:
    text = f"[tool.flet.windows]\n{initial}\n"
    output = add_windows_dependencies(text, ["new-package"])
    assert tomllib.loads(output)["tool"]["flet"]["windows"]["dependencies"] == [
        *(["existing>=1"] if "existing" in initial else []),
        "new-package",
    ]


def test_add_windows_dependencies_does_not_duplicate_table_or_items() -> None:
    text = add_windows_dependencies(
        "[tool.flet.windows]\ndependencies = []\n", ["x", "x"]
    )
    parsed = tomllib.loads(text)
    assert parsed["tool"]["flet"]["windows"]["dependencies"] == ["x"]
    assert text.count("[tool.flet.windows]") == 1


@pytest.mark.parametrize("mode", sorted(DEV_PACKAGES))
def test_prepare_metadata_generates_valid_expected_metadata(
    tmp_path: Path, mode: str
) -> None:
    ui = tmp_path / "packages" / "divergencesplitter-ui"
    runtime = tmp_path / "packages" / "divergencesplitter-runtime"
    (ui / "src").mkdir(parents=True)
    runtime.mkdir(parents=True)
    ui_pyproject = ui / "pyproject.toml"
    runtime_pyproject = runtime / "pyproject.toml"
    ui_pyproject.write_text(
        '[project]\nname="divergencesplitter-ui"\nversion="0.1.0"\ndependencies=["divergencesplitter-runtime"]\n',
        encoding="utf-8",
    )
    runtime_pyproject.write_text(
        '[project]\nname="divergencesplitter-runtime"\nversion="0.1.0"\ndependencies=["livesplit-bridge-client", "pyyaml>=6.0", "windows-capture-device-list; sys_platform == \'win32\'"]\n'
        '\n[tool.uv.sources]\nlivesplit-bridge-client={git="https://example.test/client", tag="v0.2.0"}\n'
        'windows-capture-device-list={git="https://example.test/camera", tag="v0.2.0"}\n'
        '\n[build-system]\nrequires=["uv_build"]\n',
        encoding="utf-8",
    )

    prepare_metadata(ui_pyproject, runtime_pyproject, ui, mode)
    ui_data = tomllib.loads(ui_pyproject.read_text(encoding="utf-8"))
    runtime_text = runtime_pyproject.read_text(encoding="utf-8")
    runtime_data = tomllib.loads(runtime_text)
    assert ui_data["tool"]["flet"]["dev_packages"] == DEV_PACKAGES[mode]
    assert (
        ui_data["tool"]["flet"]["windows"]["dependencies"] == WINDOWS_DEPENDENCIES[mode]
    )
    assert ui_data["tool"]["flet"]["app"] == {"path": "src", "module": "main"}
    assert ui_data["tool"]["flet"]["windows"]["compile"]["packages"] is False
    assert ui_data["tool"]["flet"]["windows"]["cleanup"]["packages"] is False
    assert (ui / "src" / "main.py").is_file()
    if mode == "pep508-git":
        assert any(
            dep.startswith("livesplit-bridge-client @ git+")
            for dep in runtime_data["project"]["dependencies"]
        )
        assert any(
            dep.startswith("windows-capture-device-list @ git+")
            for dep in runtime_data["project"]["dependencies"]
        )
        assert "[tool.uv.sources]" not in runtime_text
