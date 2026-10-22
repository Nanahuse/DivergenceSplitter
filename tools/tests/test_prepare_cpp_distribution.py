from __future__ import annotations

from pathlib import Path

import pytest
from prepare_cpp_distribution import collect_sdk_notices, prepare


def make_distribution(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "stage"
    installed = tmp_path / "installed"
    (root / "bin/platforms").mkdir(parents=True)
    (root / "licenses/msvc").mkdir(parents=True)
    (root / "licenses/msvc/MSVC-NOTICE.txt").write_text("Microsoft runtime notice")
    (installed / "vcpkg/info").mkdir(parents=True)
    packages = {
        "qtbase": [
            "Qt6Core.dll",
            "Qt6Gui.dll",
            "Qt6Widgets.dll",
            "Qt6Network.dll",
            "platforms/qwindows.dll",
        ],
        "qtwebsockets": ["Qt6WebSockets.dll"],
        "opencv4": [
            f"opencv_{component}4120.dll"
            for component in ("core", "imgproc", "imgcodecs", "img_hash", "videoio")
        ],
    }
    for package, files in packages.items():
        for name in files:
            (root / "bin" / name).write_bytes(b"runtime placeholder")
        (installed / f"vcpkg/info/{package}_1_x64-windows.list").write_text(
            "\n".join(f"x64-windows/bin/{name}" for name in files)
        )
        share = installed / "x64-windows/share" / package
        share.mkdir(parents=True)
        (share / "copyright").write_text(f"{package} license")
    for name in (
        "LICENSE",
        "DISTRIBUTION-NOTICE.txt",
        "bin/size-probe.exe",
        "bin/vcruntime140.dll",
        "bin/msvcp140.dll",
    ):
        (root / name).write_bytes(b"file placeholder")
    (root / "ndi-status.txt").write_text("UNVERIFIED: no SDK")
    (installed / "vcpkg/status").write_text(
        "Package: qtbase\nArchitecture: x64-windows\n"
    )
    manifest = tmp_path / "vcpkg.json"
    manifest.write_text("{}")
    return root, installed, manifest


def test_missing_license_fails_packaging(tmp_path: Path) -> None:
    root, installed, manifest = make_distribution(tmp_path)
    (installed / "x64-windows/share/opencv4/copyright").unlink()
    with pytest.raises(ValueError, match="License missing"):
        prepare(root, installed, manifest)


def test_unknown_dll_fails_packaging(tmp_path: Path) -> None:
    root, installed, manifest = make_distribution(tmp_path)
    (root / "bin/untracked.dll").write_bytes(b"untracked dependency")
    with pytest.raises(ValueError, match="no vcpkg owner"):
        prepare(root, installed, manifest)


def test_missing_runtime_cannot_be_masked_by_developer_machine(tmp_path: Path) -> None:
    root, installed, manifest = make_distribution(tmp_path)
    (root / "bin/msvcp140.dll").unlink()
    with pytest.raises(ValueError, match="App-local MSVC"):
        prepare(root, installed, manifest)


@pytest.mark.parametrize("plugin_under_bin", [True, False])
def test_development_files_fail_packaging(
    tmp_path: Path, plugin_under_bin: bool
) -> None:
    root, installed, manifest = make_distribution(tmp_path)
    if not plugin_under_bin:
        plugins = root / "Qt6/plugins/platforms"
        plugins.mkdir(parents=True)
        (root / "bin/platforms/qwindows.dll").rename(plugins / "qwindows.dll")
    (root / "bin/size-probe.pdb").write_bytes(b"debug symbols")
    with pytest.raises(ValueError, match="Development file"):
        prepare(root, installed, manifest)


def test_sdk_graphics_require_exact_redistributable_and_notices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "stage"
    sdk = tmp_path / "sdk"
    (root / "bin").mkdir(parents=True)
    (root / "build-metadata").mkdir()
    (sdk / "Redist/D3D/x64").mkdir(parents=True)
    (sdk / "Licenses/10.0.1.0").mkdir(parents=True)
    for name in ("d3dcompiler_47.dll", "dxcompiler.dll", "dxil.dll"):
        (root / "bin" / name).write_bytes(b"vendor binary")
        (sdk / "Redist/D3D/x64" / name).write_bytes(b"vendor binary")
    for name in ("sdk_license.rtf", "sdk_third_party_notices.rtf"):
        (sdk / "Licenses/10.0.1.0" / name).write_bytes(b"unmodified vendor notice")
    monkeypatch.setenv("WindowsSdkDir", str(sdk))
    monkeypatch.setenv("WindowsSDKVersion", "10.0.1.0\\")
    collect_sdk_notices(root)
    assert (
        root / "licenses/windows-sdk/sdk_license.rtf"
    ).read_bytes() == b"unmodified vendor notice"
    (root / "bin/dxil.dll").write_bytes(b"different vendor binary")
    with pytest.raises(ValueError, match="does not match SDK"):
        collect_sdk_notices(root)
