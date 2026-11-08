"""Collect distribution notices from installed dependencies and pinned upstreams.

The component inventory and checked-in NDI header notice live in licenses/.
Downloaded license text is cached in the ignored build directory and verified
again before each package is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
from pathlib import Path


def load_inventory(root: Path | None = None) -> dict:
    base = root if root is not None else Path(__file__).resolve().parent.parent
    path = base / "licenses" / "components.json"
    return json.loads(path.read_text(encoding="utf-8"))


def validate_destination(destination: Path, inventory: dict) -> None:
    for component in inventory["components"]:
        name = component["name"]
        license_file = component.get("license_file")
        if license_file:
            file = destination / license_file
            if not file.is_file() or not file.stat().st_size:
                raise RuntimeError(
                    f"Required license notice missing or empty: licenses/{license_file} ({name})"
                )
        elif not component.get("url"):
            raise RuntimeError(
                f"Component has neither a license file nor an official URL: {name}"
            )

    for file in destination.rglob("*"):
        if file.is_file() and not file.stat().st_size:
            raise RuntimeError(f"Empty license notice: {file}")

    transitive = destination / "vcpkg"
    if not transitive.is_dir() or not any(
        file.is_file() and file.stat().st_size for file in transitive.glob("*.txt")
    ):
        raise RuntimeError("Missing transitive vcpkg license notices")


def validate_application(root: Path, inventory: dict) -> None:
    application = inventory["application"]
    file = root / application["license_file"]
    if not file.is_file() or not file.stat().st_size:
        raise RuntimeError(f"Missing application license: {file}")


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
    imgui_source: Path | None,
    cache: Path,
) -> None:
    source_root = Path(__file__).resolve().parent.parent
    inventory = load_inventory(source_root)
    lock = json.loads(
        Path(__file__)
        .with_name("third-party-license-lock.json")
        .read_text(encoding="utf-8")
    )
    for component in inventory["components"]:
        source = component["source"]
        license_file = component.get("license_file")
        if source.startswith("vcpkg:"):
            port = source.split(":", 1)[1]
            copy_notice(share / port / "copyright", destination / license_file)
        elif source == "bridge":
            copy_notice(bridge / "LICENSE", destination / license_file)
        elif source == "pinned:camera":
            copy_notice(pinned_file(lock["camera"], cache), destination / license_file)
        elif source == "imgui":
            if imgui_source is None:
                raise RuntimeError("Dear ImGui source is required for its license")
            copy_notice(imgui_source / "LICENSE.txt", destination / license_file)
        elif source == "checked-in":
            copy_notice(source_root / "licenses" / license_file, destination / license_file)
        elif source in ("external", "bundled"):
            if not component.get("url"):
                raise RuntimeError(f"Official license URL missing: {component['name']}")
        else:
            raise RuntimeError(f"Unknown license source: {source}")

    # Preserve notices for transitive runtime dependencies too (JPEG, PNG, etc.).
    for notice in sorted(share.glob("*/copyright")):
        copy_notice(notice, destination / "vcpkg" / f"{notice.parent.name}.txt")

    validate_destination(destination, inventory)
    print(
        "Collected dependency license notices from build inputs and verified upstream sources"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--vcpkg-share", type=Path, required=True)
    parser.add_argument("--bridge-source", type=Path, required=True)
    parser.add_argument("--imgui-source", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    collect(
        args.destination,
        args.vcpkg_share,
        args.bridge_source,
        args.imgui_source,
        args.cache,
    )


if __name__ == "__main__":
    main()
