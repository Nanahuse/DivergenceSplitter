"""Prepare temporary metadata for the Flet build investigation workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "packages" / "divergencesplitter-ui"
RUNTIME = ROOT / "packages" / "divergencesplitter-runtime"


def append_once(path: Path, text: str) -> None:
    current = path.read_text(encoding="utf-8")
    if text not in current:
        path.write_text(
            current.rstrip() + "\n\n" + text.strip() + "\n", encoding="utf-8"
        )


def prepare_entry() -> None:
    (UI / "src" / "main.py").write_text(
        "from divergencesplitter_ui.main import main\n\n"
        'if __name__ == "__main__":\n    raise SystemExit(main())\n',
        encoding="utf-8",
    )
    append_once(UI / "pyproject.toml", '[tool.flet.app]\npath = "src"\nmodule = "main"')


def add_workspace_dev_packages() -> None:
    text = (UI / "pyproject.toml").read_text(encoding="utf-8")
    block = (
        "[tool.flet]\ndev_packages = {\n"
        '    "divergencesplitter-runtime" = "../divergencesplitter-runtime",\n'
        '    "divergencesplitter" = "../divergencesplitter",\n}\n'
    )
    if block not in text:
        marker = "[tool.flet.app]"
        UI.joinpath("pyproject.toml").write_text(
            text.replace(marker, block + "\n" + marker), encoding="utf-8"
        )


def replace_git_sources_with_pep508() -> None:
    text = RUNTIME.read_text(encoding="utf-8")
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
    RUNTIME.write_text(text[:start] + text[end:], encoding="utf-8")
    append_once(
        UI / "pyproject.toml",
        '[tool.flet.windows]\ndependencies = ["ndi-python>=6.3.2.4"]',
    )


def add_all_dev_packages() -> None:
    text = (UI / "pyproject.toml").read_text(encoding="utf-8")
    block = (
        "[tool.flet]\ndev_packages = {\n"
        '    "divergencesplitter-runtime" = "../divergencesplitter-runtime",\n'
        '    "divergencesplitter" = "../divergencesplitter",\n'
        '    "livesplit-bridge-client" = "../../.flet-dev-packages/livesplit-bridge-client",\n'
        '    "windows-capture-device-list" = "../../.flet-dev-packages/windows-capture-device-list",\n}\n'
        '\n[tool.flet.windows]\ndependencies = ["ndi-python>=6.3.2.4"]'
    )
    if block not in text:
        text = text.replace("[tool.flet.app]", block + "\n[tool.flet.app]")
    UI.joinpath("pyproject.toml").write_text(text, encoding="utf-8")


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
    if mode == "pep508-git":
        replace_git_sources_with_pep508()
    if mode == "all-dev-packages":
        add_all_dev_packages()


if __name__ == "__main__":
    main()
