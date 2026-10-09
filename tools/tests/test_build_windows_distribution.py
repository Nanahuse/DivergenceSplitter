from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import build_windows_distribution as bwd
import pytest
from divergencesplitter_ui.licenses import load_inventory


def make_tree(root: Path) -> None:
    """Create a minimal, complete Windows distribution output tree."""

    ui_dir = root / bwd.DIST_ROOT / bwd.UI_ARTIFACT
    ui_dir.mkdir(parents=True, exist_ok=True)
    (ui_dir / f"{bwd.UI_ARTIFACT}.exe").write_bytes(b"ui")
    notices_dir = ui_dir / "flutter_assets"
    notices_dir.mkdir(parents=True, exist_ok=True)
    (notices_dir / "NOTICES.Z").write_bytes(b"flutter notices")
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
    (ndilib / "Processing.NDI.Lib.Licenses.txt").write_bytes(b"notices")
    capture = site_packages / "windows_capture_device_list"
    capture.mkdir(parents=True, exist_ok=True)
    (capture / "core.cp314-win_amd64.pyd").write_bytes(b"pyd")

    runtime = (
        root
        / bwd.UI_PACKAGE
        / "build"
        / "flutter"
        / "build"
        / "build_python_3.14.7"
        / "python"
    )
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "python.exe").write_bytes(b"python")
    (runtime / "LICENSE.txt").write_text("Python runtime bundle", encoding="utf-8")

    inventory = {
        "schema_version": 6,
        "application": {
            "name": "DivergenceSplitter",
            "license": "MIT",
            "license_file": "application/app.txt",
        },
        "packages": [
            {
                "name": "sample-package",
                "version": "1.0",
                "license": "MIT",
                "license_file": "packages/sample.txt",
            }
        ],
        "assets": [],
    }
    inventory_path = (
        root
        / "packages"
        / "divergencesplitter-ui"
        / "src"
        / "divergencesplitter_ui"
        / "license_inventory.json"
    )
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory_text = json.dumps(inventory)
    inventory_path.write_text(inventory_text, encoding="utf-8")
    (ui_dir / "license_inventory.json").write_text(inventory_text, encoding="utf-8")
    for reference, text in {
        "application/app.txt": "application license text",
        "packages/sample.txt": "package license text",
    }.items():
        source = root / "tools" / "licenses" / reference
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(text, encoding="utf-8")


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

    def test_flet_environment_sets_encoding(self) -> None:
        env = bwd.flet_environment()

        assert env["FLET_CLI_NO_RICH_OUTPUT"] == "1"
        assert env["PYTHONUTF8"] == "1"
        assert env["PYTHONIOENCODING"] == "utf-8"


class TestVerification:
    def test_accepts_complete_tree(self, tmp_path: Path) -> None:
        make_tree(tmp_path)

        bwd.verify_ui_distribution(tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT)

    def test_copies_license_files_for_runtime_loader_and_notices(
        self, tmp_path: Path
    ) -> None:
        make_tree(tmp_path)
        ui_dir = tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT
        inventory_path = (
            tmp_path
            / "packages"
            / "divergencesplitter-ui"
            / "src"
            / "divergencesplitter_ui"
            / "license_inventory.json"
        )
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        copied = bwd.copy_inventory_license_files(
            inventory,
            source_root=tmp_path / "tools" / "licenses",
            destination_root=ui_dir / "licenses",
        )
        bwd.verify_ui_distribution(ui_dir)
        with (ui_dir / "license_inventory.json").open(encoding="utf-8") as source:
            loaded = load_inventory(source, license_root=ui_dir / "licenses")

        assert len(copied) == 2
        assert loaded.application.license_text == "application license text"
        assert loaded.packages[0].license_text == "package license text"
        assert (ui_dir / "flutter_assets" / "NOTICES.Z").is_file()

    def test_copies_flutter_notices_from_standard_windows_data_directory(
        self, tmp_path: Path
    ) -> None:
        make_tree(tmp_path)
        ui_dir = tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT
        (ui_dir / "flutter_assets" / "NOTICES.Z").unlink()
        source = ui_dir / "data" / "flutter_assets" / "NOTICES.Z"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"authoritative Flutter notices")

        bwd.verify_ui_distribution(ui_dir)

        assert (
            ui_dir / "flutter_assets" / "NOTICES.Z"
        ).read_bytes() == source.read_bytes()

    @pytest.mark.parametrize("contents", [None, b""])
    def test_rejects_missing_or_empty_flutter_notices(
        self, tmp_path: Path, contents: bytes | None
    ) -> None:
        make_tree(tmp_path)
        notices = (
            tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT / "flutter_assets" / "NOTICES.Z"
        )
        if contents is None:
            notices.unlink()
        else:
            notices.write_bytes(contents)

        with pytest.raises(
            RuntimeError, match="Required file is empty|Missing required file"
        ):
            bwd.verify_ui_distribution(tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT)

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

    def test_rejects_missing_ndi_license_notice(self, tmp_path: Path) -> None:
        make_tree(tmp_path)
        ndilib = (
            tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT / bwd.SITE_PACKAGES / "NDIlib"
        )
        (ndilib / "Processing.NDI.Lib.Licenses.txt").unlink()

        with pytest.raises(RuntimeError, match="Missing required file"):
            bwd.verify_ui_distribution(tmp_path / bwd.DIST_ROOT / bwd.UI_ARTIFACT)


class TestSmokeTest:
    def test_accepts_a_process_that_stays_alive(self) -> None:
        bwd.smoke_test_application(
            Path(sys.executable),
            args=("-c", "import time; time.sleep(30)"),
            lifetime_seconds=0.3,
        )

    def test_rejects_a_process_that_exits_early(self) -> None:
        with pytest.raises(RuntimeError, match="exited during startup"):
            bwd.smoke_test_application(
                Path(sys.executable),
                args=("-c", "import sys; sys.exit(3)"),
                lifetime_seconds=0.3,
            )


class TestOrchestration:
    def test_runs_build_and_validate(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        make_tree(tmp_path)
        runner = RecordingRunner()
        monkeypatch.setattr(bwd, "run_command", runner)
        monkeypatch.setattr(bwd, "smoke_test_application", lambda *args, **kwargs: None)

        bwd.build_windows_distribution(tmp_path)

        commands = [call[0] for call in runner.calls]
        assert any("flet" in command and "build" in command for command in commands)
        assert all("pyinstaller" not in command for command in commands)
        generated_notices = tmp_path / bwd.DIST_ROOT / "THIRD_PARTY_NOTICES.txt"
        assert generated_notices.is_file()
        assert (
            "Flet embedded Python runtime third-party notices"
            in generated_notices.read_text(encoding="utf-8")
        )
        assert "Python runtime bundle" in generated_notices.read_text(encoding="utf-8")
        assert "package license text" in generated_notices.read_text(encoding="utf-8")
        assert all(command[0] != "7z" for command in commands)

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
