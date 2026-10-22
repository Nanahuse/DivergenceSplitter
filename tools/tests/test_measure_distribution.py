from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from measure_distribution import (
    closure,
    compare_reports,
    cpp_category,
    extract_archive,
    installed_inventory,
    measure,
)


def test_actual_sizes_zip_roundtrip_and_reproducibility(tmp_path: Path) -> None:
    root = tmp_path / "distribution"
    (root / "bin").mkdir(parents=True)
    (root / "bin/app.exe").write_bytes(b"app" * 100)
    (root / "bin/shared.dll").write_bytes(b"shared" * 100)
    # Copies still take bytes in a ZIP and on disk. No fictitious deduplication.
    (root / "same.dll").write_bytes(b"shared" * 100)
    first = measure(root, tmp_path / "report1", "sample", "legacy")
    second = measure(root, tmp_path / "report2", "sample", "legacy")
    assert first["unpacked_bytes"] == 1500
    assert sum(first["categories"].values()) == 1500
    assert first["file_count"] == 3
    assert first["zip_sha256"] == second["zip_sha256"]
    with zipfile.ZipFile(tmp_path / "report1/legacy.zip") as bundle:
        assert sum(entry.file_size for entry in bundle.infolist()) == 1500
        assert bundle.read("distribution/bin/app.exe") == b"app" * 100
        assert all(
            entry.compress_type == zipfile.ZIP_DEFLATED for entry in bundle.infolist()
        )


def test_vcpkg_ownership_shared_dependency_and_feature_dependencies(
    tmp_path: Path,
) -> None:
    info = tmp_path / "vcpkg/info"
    info.mkdir(parents=True)
    (info / "zlib_1.3.1_x64-windows.list").write_text(
        "x64-windows/bin/zlib1.dll\nx64-windows/debug/bin/zlibd1.dll\n"
    )
    (tmp_path / "vcpkg/status").write_text(
        "Package: qtbase\nArchitecture: x64-windows\nDepends: zlib\n\n"
        "Package: opencv4\nArchitecture: x64-windows\nDepends: zlib\n\n"
        "Package: qtbase\nFeature: gui\nArchitecture: x64-windows\nDepends: libpng\n\n"
        "Package: zlib\nArchitecture: x64-windows\n\n"
    )
    owners, graph = installed_inventory(tmp_path)
    assert owners == {"zlib1.dll": {"zlib"}}
    qt, cv = closure(graph, {"qtbase"}), closure(graph, {"opencv4"})
    assert "libpng" in qt
    assert cpp_category("bin/zlib1.dll", owners, qt, cv) == (
        "Shared Qt/OpenCV dependencies",
        "zlib",
    )
    assert cpp_category("bin/Processing.NDI.Lib.x64.dll", owners, qt, cv)[0] == "NDI"


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "/absolute",
        "C:/drive",
        "dir/../../escape",
        "dir\\..\\escape",
        "file:stream",
    ],
)
def test_archive_rejects_unsafe_paths(tmp_path: Path, name: str) -> None:
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as bundle:
        bundle.writestr(name, b"unsafe")
    with pytest.raises(ValueError, match="Unsafe"):
        extract_archive(source, tmp_path / "destination")
    assert not (tmp_path / "destination").exists()


def test_reports_cannot_be_in_measured_tree(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="disjoint"):
        measure(tmp_path, tmp_path / "report", "sample", "legacy")


def test_compare_requires_same_compression_and_exposes_missing_ndi(
    tmp_path: Path,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "ndi-status.txt").write_text("UNVERIFIED: no SDK")
    legacy = measure(root, tmp_path / "legacy", "legacy", "legacy")
    cpp = measure(root, tmp_path / "cpp", "cpp", "cpp")
    comparison = compare_reports(legacy, cpp)
    assert "UNVERIFIED: no SDK" in comparison
    assert "not estimates" in comparison
    changed = json.loads(json.dumps(cpp))
    changed["zip_settings"]["level"] = 9
    with pytest.raises(ValueError, match="ZIP conditions differ"):
        compare_reports(legacy, changed)
