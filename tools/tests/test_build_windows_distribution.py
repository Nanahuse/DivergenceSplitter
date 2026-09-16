from __future__ import annotations

import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import build_windows_distribution as bwd
import pytest


def make_tree(root: Path) -> None:
    """Create a minimal, complete Windows distribution output tree."""

    ui_dir = root / bwd.DIST_ROOT / bwd.UI_ARTIFACT
    ui_dir.mkdir(parents=True, exist_ok=True)
    (ui_dir / f"{bwd.UI_ARTIFACT}.exe").write_bytes(b"ui")
    site_packages = ui_dir / bwd.SITE_PACKAGES
    for module in (
        "divergencesplitter",
        "divergencesplitter_runtime",
        "livesplit_bridge",
        "numpy",
        "cv2",
    ):
        (site_packages / module).mkdir(parents=True, exist_ok=True)
    cv2 = site_packages / "cv2"
    (cv2 / "config.py").write_text("# config", encoding="utf-8")
    (cv2 / "config-3.py").write_text("# config3", encoding="utf-8")
    (cv2 / "cv2.pyd").write_bytes(b"pyd")
    ndilib = site_packages / "NDIlib"
    ndilib.mkdir(parents=True, exist_ok=True)
    (ndilib / "NDIlib.cp314-win_amd64.pyd").write_bytes(b"pyd")
    (ndilib / "Processing.NDI.Lib.x64.dll").write_bytes(b"dll")
    capture = site_packages / "windows_capture_device_list"
    capture.mkdir(parents=True, exist_ok=True)
    (capture / "core.cp314-win_amd64.pyd").write_bytes(b"pyd")

    converter_dir = root / bwd.DIST_ROOT / bwd.CONVERTER_ARTIFACT
    converter_dir.mkdir(parents=True, exist_ok=True)
    (converter_dir / f"{bwd.CONVERTER_ARTIFACT}.exe").write_bytes(b"converter")


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], Path | None, Mapping[str, str] | None]] = []

    def __call__(
        self,
        args: Sequence[str],
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(args), cwd, env))
        if "--help" in args:
            return subprocess.CompletedProcess(list(args), 0)
        if "--definitely-invalid-option" in args:
            return subprocess.CompletedProcess(list(args), bwd.INVALID_OPTION_EXIT_CODE)
        return subprocess.CompletedProcess(list(args), 0)


class TestBuildCommands:
    def test_flet_build_uses_production_metadata(self) -> None:
        command = bwd.flet_build_command()

        assert command[:7] == [
            "uv",
            "run",
            "--no-sync",
            "flet",
            "build",
            "windows",
            bwd.UI_PACKAGE.as_posix(),
        ]
        assert "--artifact" in command
        assert command[command.index("--artifact") + 1] == bwd.UI_ARTIFACT
        assert (
            command[command.index("--output") + 1]
            == (bwd.DIST_ROOT / bwd.UI_ARTIFACT).as_posix()
        )
        assert "--no-compile-packages" not in command
        assert "--no-cleanup-packages" not in command

    def test_converter_build_stays_pyinstaller(self) -> None:
        command = bwd.converter_build_command()

        assert "pyinstaller" in command
        assert "--onedir" in command
        assert "--windowed" in command
        assert "--clean" in command
        assert command[command.index("--name") + 1] == bwd.CONVERTER_ARTIFACT
        assert "flet" not in command

    def test_flet_environment_sets_encoding(self) -> None:
        env = bwd.flet_environment()

        assert env["FLET_CLI_NO_RICH_OUTPUT"] == "1"
        assert env["PYTHONUTF8"] == "1"
        assert env["PYTHONIOENCODING"] == "utf-8"

    def test_archive_commands_use_bundled_names(self, tmp_path: Path) -> None:
        archive = tmp_path / "out.7z"

        create = bwd.archive_create_command(archive)
        assert create[:3] == ["7z", "a", "-t7z"]
        assert create[3] == archive.as_posix()
        assert create[4:] == [bwd.UI_ARTIFACT, bwd.CONVERTER_ARTIFACT]

        assert bwd.archive_test_command(archive) == ["7z", "t", archive.as_posix()]


class TestVerification:
    def test_accepts_complete_tree(self, tmp_path: Path) -> None:
        make_tree(tmp_path)

        bwd.verify_ui_distribution(tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT)
        bwd.verify_converter_distribution(
            tmp_path / bwd.DIST_ROOT / bwd.CONVERTER_ARTIFACT
        )

    def test_rejects_missing_ui_executable(self, tmp_path: Path) -> None:
        make_tree(tmp_path)
        (tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT / f"{bwd.UI_ARTIFACT}.exe").unlink()

        with pytest.raises(RuntimeError, match="Missing required file"):
            bwd.verify_ui_distribution(tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT)

    def test_rejects_missing_opencv_config(self, tmp_path: Path) -> None:
        make_tree(tmp_path)
        cv2 = tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT / bwd.SITE_PACKAGES / "cv2"
        (cv2 / "config-3.py").unlink()

        with pytest.raises(RuntimeError, match="Missing required file"):
            bwd.verify_ui_distribution(tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT)

    def test_rejects_empty_converter_executable(self, tmp_path: Path) -> None:
        make_tree(tmp_path)
        exe = (
            tmp_path
            / bwd.DIST_ROOT
            / bwd.CONVERTER_ARTIFACT
            / f"{bwd.CONVERTER_ARTIFACT}.exe"
        )
        exe.write_bytes(b"")

        with pytest.raises(RuntimeError, match="empty"):
            bwd.verify_converter_distribution(
                tmp_path / bwd.DIST_ROOT / bwd.CONVERTER_ARTIFACT
            )


class TestSmokeTest:
    def test_accepts_expected_exit_codes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(bwd, "run_command", RecordingRunner())

        bwd.smoke_test_cli(tmp_path / "app.exe")

    def test_rejects_unexpected_help_exit_code(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def runner(args, *, cwd=None, env=None, check=True):
            return subprocess.CompletedProcess(list(args), 7)

        monkeypatch.setattr(bwd, "run_command", runner)

        with pytest.raises(RuntimeError, match="--help"):
            bwd.smoke_test_cli(tmp_path / "app.exe")


class TestOrchestration:
    def test_runs_build_validate_and_archive(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        make_tree(tmp_path)
        runner = RecordingRunner()
        monkeypatch.setattr(bwd, "run_command", runner)

        bwd.build_windows_distribution(tmp_path)

        commands = [call[0] for call in runner.calls]
        assert any("flet" in command and "build" in command for command in commands)
        assert any("pyinstaller" in command for command in commands)
        assert any(command[:2] == ["7z", "a"] for command in commands)
        assert any(command[:2] == ["7z", "t"] for command in commands)

    def test_propagates_build_failure(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        def runner(args, *, cwd=None, env=None, check=True):
            raise subprocess.CalledProcessError(1, list(args))

        monkeypatch.setattr(bwd, "run_command", runner)

        with pytest.raises(subprocess.CalledProcessError):
            bwd.build_windows_distribution(tmp_path)

    def test_fails_when_ui_artifact_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(bwd, "run_command", RecordingRunner())

        with pytest.raises(RuntimeError):
            bwd.build_windows_distribution(tmp_path)
