"""Measure logical distribution bytes and create comparable deterministic ZIPs.

Uses only Python's standard library. Each deployed path is counted once. Equal
contents at different paths still occupy distribution bytes and are not deducted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import shutil
import zipfile
import zlib
from collections import Counter
from pathlib import Path
from typing import Any

ZIP_SETTINGS = {
    "method": "DEFLATE",
    "level": 6,
    "timestamp": "2020-01-01T00:00:00",
    "ordering": "relative path, case sensitive",
    "python": platform.python_version(),
    "zlib": zlib.ZLIB_RUNTIME_VERSION,
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_archive(archive: Path, destination: Path) -> None:
    """Reject traversal, links, Windows drive paths and ambiguous ZIP entries."""
    if destination.exists():
        raise ValueError(f"Extraction directory must be new: {destination}")
    with zipfile.ZipFile(archive) as bundle:
        seen: set[str] = set()
        for member in bundle.infolist():
            name = member.filename.replace("\\", "/")
            parts = name.rstrip("/").split("/")
            key = name.rstrip("/").casefold()
            if (
                name.startswith("/")
                or any(
                    p in ("", ".", "..") or ":" in p or p.endswith((" ", "."))
                    for p in parts
                )
                or (member.external_attr >> 16) & 0o170000 == 0o120000
                or key in seen
            ):
                raise ValueError(f"Unsafe/ambiguous ZIP entry: {member.filename}")
            seen.add(key)
        destination.mkdir(parents=True)
        bundle.extractall(destination)


def installed_inventory(
    installed: Path,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Read vcpkg's installed file lists and dependency graph, not DLL guesses."""
    owners: dict[str, set[str]] = {}
    graph: dict[str, set[str]] = {}
    for listing in sorted((installed / "vcpkg" / "info").glob("*_x64-windows.list")):
        package = listing.name.split("_", 1)[0]
        for line in listing.read_text(encoding="utf-8").splitlines():
            if line.lower().endswith(".dll") and "/debug/" not in line.lower():
                owners.setdefault(Path(line).name.casefold(), set()).add(package)
    status = installed / "vcpkg" / "status"
    if not status.is_file():
        raise ValueError(f"Missing vcpkg installed status: {status}")
    for paragraph in status.read_text(encoding="utf-8").split("\n\n"):
        fields: dict[str, str] = {}
        for line in paragraph.splitlines():
            if ": " in line and not line.startswith(" "):
                key, value = line.split(": ", 1)
                fields[key] = value
        if fields.get("Architecture") != "x64-windows" or "Package" not in fields:
            continue
        dependencies = {
            re.split(r"[\s:\[]", value.strip(), maxsplit=1)[0]
            for value in fields.get("Depends", "").split(",")
            if value.strip()
        }
        graph.setdefault(fields["Package"], set()).update(dependencies)
    return owners, graph


def closure(graph: dict[str, set[str]], roots: set[str]) -> set[str]:
    found: set[str] = set()
    pending = list(roots)
    while pending:
        package = pending.pop()
        if package not in found:
            found.add(package)
            pending.extend(graph.get(package, set()))
    return found


def legacy_category(path: str) -> str:
    lower = path.casefold()
    parts = lower.split("/")
    name = parts[-1]
    if "ndilib" in parts or "processing.ndi." in name or "ndi-python" in lower:
        return "NDI"
    if any(p == "cv2" or p.startswith(("opencv", "numpy")) for p in parts):
        return "OpenCV (including NumPy)"
    if (
        "flutter" in lower
        or "flet" in lower
        or name.startswith("dart")
        or name in ("app.so", "icudtl.dat")
    ):
        return "Flet/Flutter"
    if name.startswith(
        ("vcruntime", "msvcp", "concrt", "vccorlib", "vcomp", "vc_redist")
    ):
        return "MSVC Runtime"
    if name == "divergencesplitter.exe":
        return "Application"
    if (
        "site-packages" in parts
        or "dlls" in parts
        or "python" in lower
        or name.endswith((".pyc", ".pyd"))
    ):
        return "Python (runtime + other packages)"
    return "Other"


def cpp_category(
    path: str, owners: dict[str, set[str]], qt: set[str], cv: set[str]
) -> tuple[str, str]:
    name = Path(path).name.casefold()
    if name == "size-probe.exe":
        return "Application", "project"
    if name in ("d3dcompiler_47.dll", "dxcompiler.dll", "dxil.dll"):
        return (
            "Windows SDK graphics runtime (Qt deployment)",
            "Microsoft Windows SDK redistributable",
        )
    if "processing.ndi." in name or path.startswith("licenses/ndi/"):
        return "NDI", "official SDK"
    if name.startswith(
        ("vcruntime", "msvcp", "concrt", "vccorlib", "vcomp", "vc_redist")
    ):
        return "MSVC Runtime", "MSVC redistributable"
    packages = owners.get(name, set())
    owner = ", ".join(sorted(packages))
    if packages & qt and packages & cv:
        return "Shared Qt/OpenCV dependencies", owner
    if packages & qt:
        return "Qt (including dependencies/plugins)", owner
    if packages & cv:
        return "OpenCV (including dependencies)", owner
    if path.startswith(("licenses/", "build-metadata/")) or name.endswith(".txt"):
        return "Notices and metadata", owner
    return "Other", owner


def measure(
    root: Path, output: Path, label: str, kind: str, installed: Path | None = None
) -> dict[str, Any]:
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("Distribution and report directories must be disjoint")
    files = sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix())
    if not root.is_dir() or any(p.is_symlink() or p.is_junction() for p in files):
        raise ValueError("Distribution must exist and contain no symlinks/junctions")
    owners, graph = installed_inventory(installed) if installed else ({}, {})
    qt = closure(graph, {"qtbase", "qtwebsockets"})
    cv = closure(graph, {"opencv4"})
    totals: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{kind}.zip"
    # Store the same path prefix for both variants; no report files inside ZIP.
    with zipfile.ZipFile(
        archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as bundle:
        for path in files:
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            category, owner = (
                cpp_category(relative, owners, qt, cv)
                if kind == "cpp"
                else (legacy_category(relative), "path heuristic")
            )
            size = path.stat().st_size
            totals[category] += size
            rows.append(
                {
                    "path": relative,
                    "bytes": size,
                    "category": category,
                    "owner": owner,
                    "sha256": sha256(path),
                }
            )
            info = zipfile.ZipInfo(f"distribution/{relative}", (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            # ZipFile.open uses ZipInfo's compression level (public since 3.13).
            info.compress_level = 6
            with (
                path.open("rb") as source,
                bundle.open(info, "w", force_zip64=True) as target,
            ):
                shutil.copyfileobj(source, target, length=1024 * 1024)
    if not rows:
        raise ValueError("Distribution contains no files")
    report: dict[str, Any] = {
        "schema": 1,
        "label": label,
        "kind": kind,
        "measurement": "measured",
        "classification": "vcpkg ownership + dependency graph"
        if installed
        else "path heuristic",
        "unpacked_bytes": sum(totals.values()),
        "zip_bytes": archive.stat().st_size,
        "zip_sha256": sha256(archive),
        "zip_settings": ZIP_SETTINGS,
        "categories": dict(sorted(totals.items())),
        "file_count": len(rows),
        "files": rows,
    }
    ndi_status = root / "ndi-status.txt"
    report["ndi_status"] = (
        ndi_status.read_text(encoding="utf-8").strip()
        if ndi_status.is_file()
        else "Not evaluated by this tool"
    )
    return report


def render_report(report: dict[str, Any]) -> str:
    lines = [
        f"# {report['label']}",
        "",
        "Measured logical file bytes (MB = 1,000,000 bytes; MiB = 1,048,576 bytes).",
        "",
        f"- Files: {report['file_count']}",
        f"- Unpacked: {report['unpacked_bytes']:,} bytes",
        f"- ZIP: {report['zip_bytes']:,} bytes",
        f"- NDI: {report['ndi_status']}",
        f"- Classification: {report['classification']}",
        "",
        "| Category | Bytes | MiB |",
        "| --- | ---: | ---: |",
    ]
    for category, size in report["categories"].items():
        lines.append(f"| {category} | {size:,} | {size / 1048576:.2f} |")
    lines += [
        "",
        "Every deployed path is counted once. Identical DLLs at different paths remain part of the actual size.",
        "Legacy ownership uses path heuristics. Shared Qt/OpenCV DLLs have their own category.",
        "",
        "ZIP conditions: `" + json.dumps(report["zip_settings"], sort_keys=True) + "`",
        "",
    ]
    return "\n".join(lines)


def compare_reports(legacy: dict[str, Any], cpp: dict[str, Any]) -> str:
    if legacy["kind"] != "legacy" or cpp["kind"] != "cpp":
        raise ValueError("Comparison requires legacy and cpp reports in that order")
    if legacy["zip_settings"] != cpp["zip_settings"]:
        raise ValueError(
            "ZIP conditions differ; remeasure both distributions with the same Python/zlib"
        )
    lines = [
        "# Distribution comparison",
        "",
        "Both rows below are measurements, not estimates of a complete C++ port.",
        "",
        "| Distribution | Unpacked bytes | ZIP bytes |",
        "| --- | ---: | ---: |",
    ]
    for report in (legacy, cpp):
        lines.append(
            f"| {report['label']} | {report['unpacked_bytes']:,} | {report['zip_bytes']:,} |"
        )
    lines += [
        "",
        f"C++ NDI status: {cpp['ndi_status']}",
        "",
        "The probe excludes Scenario Runtime, full UI, detectors, product assets and settings.",
        "No numerical estimate for these unimplemented parts is made. The probe is a dependency-size baseline.",
        "If NDI is unverified, the C++ total excludes it and is not the complete requested configuration.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sources = parser.add_mutually_exclusive_group(required=True)
    sources.add_argument("--root", type=Path)
    sources.add_argument("--source-zip", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--kind", required=True, choices=("legacy", "cpp"))
    parser.add_argument("--label", required=True)
    parser.add_argument("--vcpkg-installed", type=Path)
    parser.add_argument("--legacy-report", type=Path)
    parser.add_argument("--provenance", default="Not supplied")
    args = parser.parse_args()
    if args.kind == "cpp" and args.vcpkg_installed is None:
        parser.error("C++ reports require --vcpkg-installed for dependency ownership")
    root = args.root
    if args.source_zip:
        root = args.output.parent / f"{args.output.name}-extracted"
        extract_archive(args.source_zip, root)
    report = measure(root, args.output, args.label, args.kind, args.vcpkg_installed)
    report["provenance"] = args.provenance
    if args.source_zip:
        report["source_artifact"] = {
            "bytes": args.source_zip.stat().st_size,
            "sha256": sha256(args.source_zip),
        }
    (args.output / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (args.output / "report.md").write_text(render_report(report), encoding="utf-8")
    with (args.output / "files.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=("path", "bytes", "category", "owner", "sha256")
        )
        writer.writeheader()
        writer.writerows(report["files"])
    if args.legacy_report:
        legacy = json.loads(args.legacy_report.read_text(encoding="utf-8"))
        (args.output / "comparison.md").write_text(
            compare_reports(legacy, report), encoding="utf-8"
        )
    print(render_report(report))


if __name__ == "__main__":
    main()
