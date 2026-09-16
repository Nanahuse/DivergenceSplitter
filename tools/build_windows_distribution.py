"""Build and verify the Windows distribution archive.

This module is the production build orchestrator. GitHub Actions only prepares
the environment (setup ``uv`` and ``uv sync``) and then runs this script; every
build, validation, and archive step lives here so it can be tested without a
real Flet/Flutter build.

Order of work:

1. Build the Flet Windows application.
2. Build the AutoSplit converter with PyInstaller.
3. Validate the UI and converter output trees.
4. Smoke test the UI executable.
5. Create and verify the 7z distribution archive.

The workflow generates the UI version module (``tools/generate_ui_version.py``)
immediately before this script. The Flet metadata in
``packages/divergencesplitter-ui/pyproject.toml`` is the authority for the
build; this script never rewrites project metadata and never builds its own
``uv`` environment.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

UI_PACKAGE = Path("packages") / "divergencesplitter-ui"

UI_ARTIFACT = "DivergenceSplitter"
CONVERTER_ARTIFACT = "autosplit-converter"
DIST_ROOT = Path("dist") / "windows"
ARCHIVE_PATH = Path("dist") / "DivergenceSplitter-windows-x64.7z"

SITE_PACKAGES = "site-packages"
INVALID_OPTION_EXIT_CODE = 2


def run_command(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run one external command without a shell."""

    return subprocess.run(
        list(args),
        cwd=None if cwd is None else str(cwd),
        env=None if env is None else dict(env),
        check=check,
        text=True,
    )


def flet_environment() -> dict[str, str]:
    """Return the environment the Flet subprocess needs to build cleanly."""

    env = os.environ.copy()
    env["FLET_CLI_NO_RICH_OUTPUT"] = "1"
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def flet_build_command() -> list[str]:
    """Flet Windows build command; compile/cleanup live in project metadata."""

    return [
        "uv",
        "run",
        "--no-sync",
        "flet",
        "build",
        "windows",
        UI_PACKAGE.as_posix(),
        "--yes",
        "--no-rich-output",
        "--artifact",
        UI_ARTIFACT,
        "--product",
        UI_ARTIFACT,
        "--output",
        (DIST_ROOT / UI_ARTIFACT).as_posix(),
    ]


def converter_build_command() -> list[str]:
    """AutoSplit converter build command; the converter stays on PyInstaller."""

    return [
        "uv",
        "run",
        "--no-sync",
        "pyinstaller",
        "--onedir",
        "--windowed",
        "--clean",
        "--name",
        CONVERTER_ARTIFACT,
        "--distpath",
        DIST_ROOT.as_posix(),
        "--workpath",
        (Path("build") / "converter-pyinstaller").as_posix(),
        "--specpath",
        (Path("build") / "converter-pyinstaller").as_posix(),
        (Path("tools") / "converter_entry.py").as_posix(),
    ]


def archive_create_command(archive: Path) -> list[str]:
    """7z the two built directory distributions into one archive."""

    return [
        "7z",
        "a",
        "-t7z",
        archive.as_posix(),
        UI_ARTIFACT,
        CONVERTER_ARTIFACT,
    ]


def archive_test_command(archive: Path) -> list[str]:
    """Verify the created archive with the 7z test command."""

    return ["7z", "t", archive.as_posix()]


def require_file(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"Missing required file: {path}")


def require_nonempty_file(path: Path) -> None:
    require_file(path)
    if path.stat().st_size == 0:
        raise RuntimeError(f"Required file is empty: {path}")


def require_dir(path: Path) -> None:
    if not path.is_dir():
        raise RuntimeError(f"Missing required directory: {path}")


def require_glob(directory: Path, pattern: str, description: str) -> Path:
    require_dir(directory)
    for match in sorted(directory.glob(pattern)):
        if match.is_file():
            return match
    raise RuntimeError(f"Missing required {description}: {directory / pattern}")


def verify_ui_distribution(ui_dir: Path) -> None:
    """Validate the Flet build output tree and its native dependencies."""

    require_nonempty_file(ui_dir / f"{UI_ARTIFACT}.exe")

    site_packages = ui_dir / SITE_PACKAGES
    require_dir(site_packages)
    for module in (
        "divergencesplitter",
        "divergencesplitter_runtime",
        "livesplit_bridge",
        "numpy",
        "cv2",
    ):
        require_dir(site_packages / module)

    cv2 = site_packages / "cv2"
    require_file(cv2 / "config.py")
    require_file(cv2 / "config-3.py")
    require_file(cv2 / "cv2.pyd")

    ndilib = site_packages / "NDIlib"
    require_glob(ndilib, "NDIlib*.pyd", "NDI extension module")
    require_glob(ndilib, "*.dll", "NDI runtime DLL")

    capture = site_packages / "windows_capture_device_list"
    require_glob(capture, "core*.pyd", "capture-device extension module")


def verify_converter_distribution(converter_dir: Path) -> None:
    """Validate the PyInstaller converter output tree."""

    require_nonempty_file(converter_dir / f"{CONVERTER_ARTIFACT}.exe")


def smoke_test_cli(executable: Path) -> None:
    """Run the packaged application CLI contracts."""

    help_result = run_command([str(executable), "--help"], check=False)
    if help_result.returncode != 0:
        raise RuntimeError(
            f"{executable} --help failed with exit code {help_result.returncode}"
        )

    invalid_result = run_command(
        [str(executable), "--definitely-invalid-option"], check=False
    )
    if invalid_result.returncode != INVALID_OPTION_EXIT_CODE:
        raise RuntimeError(
            f"{executable} --definitely-invalid-option exited with "
            f"{invalid_result.returncode}, expected {INVALID_OPTION_EXIT_CODE}"
        )


def build_windows_distribution(root: Path = REPO_ROOT) -> None:
    """Run the full Windows distribution build and return when verified."""

    run_command(flet_build_command(), cwd=root, env=flet_environment())
    run_command(converter_build_command(), cwd=root)

    ui_dir = root / DIST_ROOT / UI_ARTIFACT
    converter_dir = root / DIST_ROOT / CONVERTER_ARTIFACT
    verify_ui_distribution(ui_dir)
    verify_converter_distribution(converter_dir)

    smoke_test_cli(ui_dir / f"{UI_ARTIFACT}.exe")

    archive = root / ARCHIVE_PATH
    run_command(archive_create_command(archive), cwd=root / DIST_ROOT)
    run_command(archive_test_command(archive), cwd=root / DIST_ROOT)
    print(f"Built and verified {archive}")


def main() -> None:
    build_windows_distribution()


if __name__ == "__main__":
    main()
