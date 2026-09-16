"""Prepare temporary metadata for the Flet build investigation workflow."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "packages" / "divergencesplitter-ui"
UI_PYPROJECT = UI / "pyproject.toml"
RUNTIME = ROOT / "packages" / "divergencesplitter-runtime"
RUNTIME_PYPROJECT = RUNTIME / "pyproject.toml"


def append_once(path: Path, text: str) -> None:
    current = path.read_text(encoding="utf-8")
    if text not in current:
        path.write_text(
            current.rstrip() + "\n\n" + text.strip() + "\n", encoding="utf-8"
        )


def add_windows_dependencies(dependencies: list[str]) -> None:
    text = UI_PYPROJECT.read_text(encoding="utf-8")
    section = re.search(r"(?ms)^\[tool\.flet\.windows\]\s*\n(.*?)(?=^\[|\Z)", text)
    if section is None:
        text = text.rstrip() + "\n\n[tool.flet.windows]\ndependencies = []\n"
        section = re.search(r"(?ms)^\[tool\.flet\.windows\]\s*\n(.*?)(?=^\[|\Z)", text)
    assert section is not None
    body = section.group(1)
    match = re.search(r"(?ms)^dependencies\s*=\s*\[(.*?)^\]", body)
    if match is None:
        body = body.rstrip() + "\ndependencies = []\n"
        match = re.search(r"(?ms)^dependencies\s*=\s*\[(.*?)^\]", body)
    assert match is not None
    entries = match.group(1)
    for dependency in dependencies:
        rendered = f'"{dependency}"'
        if rendered not in entries:
            entries += f"\n    {rendered},"
    body = body[: match.start(1)] + entries + body[match.end(1) :]
    text = text[: section.start(1)] + body + text[section.end(1) :]
    UI_PYPROJECT.write_text(text, encoding="utf-8")


def prepare_entry() -> None:
    (UI / "src" / "main.py").write_text(
        "from divergencesplitter_ui.main import main\n\n"
        'if __name__ == "__main__":\n    raise SystemExit(main())\n',
        encoding="utf-8",
    )
    append_once(UI_PYPROJECT, '[tool.flet.app]\npath = "src"\nmodule = "main"')


def add_workspace_dev_packages() -> None:
    text = UI_PYPROJECT.read_text(encoding="utf-8")
    block = (
        "[tool.flet.dev_packages]\n"
        'divergencesplitter-runtime = "../divergencesplitter-runtime"\n'
        'divergencesplitter = "../divergencesplitter"\n'
    )
    if block not in text:
        UI_PYPROJECT.write_text(
            text.replace("[tool.flet.app]", block + "\n[tool.flet.app]"),
            encoding="utf-8",
        )


def replace_git_sources_with_pep508() -> None:
    text = RUNTIME_PYPROJECT.read_text(encoding="utf-8")
    text = text.replace(
        '    "livesplit-bridge-client",',
        '    "livesplit-bridge-client @ git+https://github.com/Nanahuse/livesplit-bridge-client.git@v0.2.0",',
    )
    text = text.replace(
        "    \"windows-capture-device-list; sys_platform == 'win32'\",",
        "    \"windows-capture-device-list @ git+https://github.com/Nanahuse/windows-capture-device-list.git@v0.2.0; sys_platform == 'win32'\",",
    )
    start = text.index("\n[tool.uv.sources]")
    end = text.index("\n[build-system]", start)
    RUNTIME_PYPROJECT.write_text(text[:start] + text[end:], encoding="utf-8")
    add_windows_dependencies(["divergencesplitter", "ndi-python>=6.3.2.4"])


def add_all_dev_packages() -> None:
    text = UI_PYPROJECT.read_text(encoding="utf-8")
    block = (
        "[tool.flet.dev_packages]\n"
        'divergencesplitter-runtime = "../divergencesplitter-runtime"\n'
        'divergencesplitter = "../divergencesplitter"\n'
        'livesplit-bridge-client = "../../.flet-dev-packages/livesplit-bridge-client"\n'
        'windows-capture-device-list = "../../.flet-dev-packages/windows-capture-device-list"\n'
    )
    if block not in text:
        text = text.replace("[tool.flet.app]", block + "\n[tool.flet.app]")
    UI_PYPROJECT.write_text(text, encoding="utf-8")
    add_windows_dependencies(
        [
            "divergencesplitter",
            "livesplit-bridge-client",
            "windows-capture-device-list",
            "ndi-python>=6.3.2.4",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode",
        choices=[
            "entry-only",
            "workspace-dev-packages",
            "pep508-git",
            "all-dev-packages",
        ],
    )
    mode = parser.parse_args().mode
    prepare_entry()
    if mode in {"workspace-dev-packages", "pep508-git"}:
        add_workspace_dev_packages()
    if mode == "workspace-dev-packages":
        add_windows_dependencies(["divergencesplitter"])
    if mode == "pep508-git":
        replace_git_sources_with_pep508()
    if mode == "all-dev-packages":
        add_all_dev_packages()


if __name__ == "__main__":
    main()
