"""Collect distribution notices from installed dependencies and pinned upstreams.

Only acquisition metadata lives in Git. Downloaded license text is cached in
the ignored build directory and verified again before each package is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def pinned_file(entry: dict[str, str], cache: Path) -> Path:
    destination = cache / entry["sha256"]
    if (
        not destination.is_file()
        or hashlib.sha256(destination.read_bytes()).hexdigest() != entry["sha256"]
    ):
        with urllib.request.urlopen(entry["url"], timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise RuntimeError(f"Upstream license SHA-256 mismatch: {entry['name']}")
        cache.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return destination


def copy_notice(source: Path, destination: Path) -> None:
    if not source.is_file() or not source.stat().st_size:
        raise RuntimeError(f"Required dependency notice missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def collect(
    destination: Path,
    share: Path,
    bridge: Path,
    qt_dir: Path | None,
    qt_version: str,
    cache: Path,
) -> None:
    lock = json.loads(
        Path(__file__)
        .with_name("third-party-license-lock.json")
        .read_text(encoding="utf-8")
    )
    required = {
        "boost": "boost-asio",
        "opencv": "opencv4",
        "yaml-cpp": "yaml-cpp",
        "nlohmann-json": "nlohmann-json",
    }
    for name, port in required.items():
        copy_notice(share / port / "copyright", destination / f"{name}.txt")
    # Preserve notices for transitive runtime dependencies too (JPEG, PNG, etc.).
    for notice in sorted(share.glob("*/copyright")):
        copy_notice(notice, destination / "vcpkg" / f"{notice.parent.name}.txt")
    copy_notice(bridge / "LICENSE", destination / "livesplit-bridge-client-cpp.txt")
    copy_notice(
        pinned_file(lock["camera"], cache), destination / lock["camera"]["name"]
    )
    if qt_dir is not None:
        installed = qt_dir.parent / "qtbase/copyright"
        if installed.is_file():
            copy_notice(installed, destination / "qtbase.txt")
        else:
            qt = lock["qt"]
            if qt_version != qt["version"]:
                raise RuntimeError(
                    "External Qt license pin differs from Qt version; update the license lock"
                )
            with ThreadPoolExecutor(max_workers=8) as pool:
                sources = list(
                    pool.map(lambda entry: pinned_file(entry, cache), qt["files"])
                )
            # Match the Qt/vcpkg license bundle format without storing a copy in Git.
            with (destination / "qtbase.txt").open("wb") as output:
                for entry, source in zip(qt["files"], sources, strict=True):
                    output.write(f"{entry['name']}:\n\n".encode())
                    output.write(source.read_bytes())
                    output.write(b"\n\n")
    print(
        "Collected dependency license notices from build inputs and verified upstream sources"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--vcpkg-share", type=Path, required=True)
    parser.add_argument("--bridge-source", type=Path, required=True)
    parser.add_argument("--qt-dir", type=Path)
    parser.add_argument("--qt-version", default="")
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    collect(
        args.destination,
        args.vcpkg_share,
        args.bridge_source,
        args.qt_dir,
        args.qt_version,
        args.cache,
    )


if __name__ == "__main__":
    main()
