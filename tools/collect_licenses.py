"""Collect distribution notices from installed dependencies and pinned upstreams.

The component inventory and checked-in NDI header notice live in licenses/.
Downloaded license text is cached in the ignored build directory and verified
again before each package is created.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import urllib.request
from email.parser import Parser
from pathlib import Path


DISTRIBUTIONS = ("combined", "divergencesplitter", "scenario-builder")


def load_inventory(root: Path | None = None) -> dict:
    base = root if root is not None else Path(__file__).resolve().parent.parent
    path = base / "licenses" / "components.json"
    return json.loads(path.read_text(encoding="utf-8"))


def distribution_inventory(distribution: str) -> dict:
    inventory = load_inventory()
    if distribution != "combined":
        inventory["components"] = [
            component for component in inventory["components"]
            if component.get("product", distribution) == distribution
        ]
    if distribution == "scenario-builder":
        inventory["application"]["name"] = "Scenario Builder"
    return inventory


def vcpkg_roots(inventory: dict) -> set[str]:
    return {
        source.split(":", 1)[1]
        for component in inventory["components"]
        if (source := component["source"]).startswith("vcpkg:")
    }


def dependency_ports(share: Path, roots: set[str]) -> list[str]:
    triplet = share.parent.name
    status = share.parents[1] / "vcpkg" / "status"
    dependencies: dict[str, set[str]] = {}
    parser = Parser()
    for paragraph in status.read_text(encoding="utf-8").strip().split("\n\n"):
        package = parser.parsestr(paragraph)
        if package["Architecture"] == triplet and package["Status"] == "install ok installed":
            dependencies.setdefault(package["Package"], set()).update(
                dependency.strip() for dependency in package.get("Depends", "").split(",")
                if dependency.strip()
            )

    pending = set(roots)
    included = set()
    while pending:
        port = pending.pop()
        # vcpkg helpers and the Boost uninstall port are used only at build time.
        if port in included or port.startswith("vcpkg-") or port == "boost-uninstall":
            continue
        if port not in dependencies:
            raise RuntimeError(f"Missing installed vcpkg package: {port} ({triplet})")
        included.add(port)
        pending.update(dependencies[port])
    return sorted(included)


def has_notice(file: Path) -> bool:
    return file.is_file() and bool(file.read_bytes().strip())


def validate_destination(destination: Path, inventory: dict) -> None:
    for component in inventory["components"]:
        name = component["name"]
        license_file = component.get("license_file")
        if license_file:
            file = destination / license_file
            if not has_notice(file):
                raise RuntimeError(
                    f"Required license notice missing or empty: licenses/{license_file} ({name})"
                )
        elif not component.get("url"):
            raise RuntimeError(
                f"Component has neither a license file nor an official URL: {name}"
            )

    ports = inventory.get("vcpkg_notices")
    if not isinstance(ports, list) or not all(
        isinstance(port, str) and re.fullmatch(r"[a-z0-9-]+", port) for port in ports
    ) or not vcpkg_roots(inventory).issubset(ports):
        raise RuntimeError("Missing transitive vcpkg license notices")
    for port in ports:
        file = destination / "vcpkg" / f"{port}.txt"
        if not has_notice(file):
            raise RuntimeError(f"Missing or empty transitive vcpkg license notice: {port}")

    for file in destination.rglob("*"):
        if file.is_file() and not has_notice(file):
            raise RuntimeError(f"Empty license notice: {file}")


def validate_application(root: Path, inventory: dict) -> None:
    application = inventory["application"]
    file = root / application["license_file"]
    if not has_notice(file):
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
    if not has_notice(source):
        raise RuntimeError(f"Required dependency notice missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def collect(
    destination: Path,
    share: Path,
    bridge: Path | None,
    imgui_source: Path | None,
    cache: Path,
    implot_source: Path | None = None,
    *,
    distribution: str = "combined",
    frontend: Path | None = None,
) -> None:
    source_root = Path(__file__).resolve().parent.parent
    inventory = distribution_inventory(distribution)
    for component in inventory["components"]:
        source = component["source"]
        license_file = component.get("license_file")
        if source.startswith("vcpkg:"):
            port = source.split(":", 1)[1]
            copy_notice(share / port / "copyright", destination / license_file)
        elif source.startswith("npm:"):
            if frontend is None:
                raise RuntimeError("Built frontend dependencies are required for their licenses")
            package = source.split(":", 1)[1]
            copy_notice(frontend / "node_modules" / package / "LICENSE", destination / license_file)
        elif source == "bridge":
            if bridge is None:
                raise RuntimeError("LiveSplit Bridge source is required for its license")
            copy_notice(bridge / "LICENSE", destination / license_file)
        elif source == "pinned:camera":
            lock = json.loads(
                Path(__file__).with_name("third-party-license-lock.json").read_text(encoding="utf-8")
            )
            copy_notice(pinned_file(lock["camera"], cache), destination / license_file)
        elif source == "imgui":
            if imgui_source is None:
                raise RuntimeError("Dear ImGui source is required for its license")
            copy_notice(imgui_source / "LICENSE.txt", destination / license_file)
        elif source == "implot":
            if implot_source is None:
                raise RuntimeError("ImPlot source is required for its license")
            copy_notice(implot_source / "LICENSE", destination / license_file)
        elif source == "checked-in":
            copy_notice(source_root / "licenses" / license_file, destination / license_file)
        elif source in ("external", "bundled"):
            if not component.get("url"):
                raise RuntimeError(f"Official license URL missing: {component['name']}")
        else:
            raise RuntimeError(f"Unknown license source: {source}")

    ports = dependency_ports(share, vcpkg_roots(inventory))
    for port in ports:
        copy_notice(share / port / "copyright", destination / "vcpkg" / f"{port}.txt")

    inventory["vcpkg_notices"] = ports
    validate_destination(destination, inventory)
    (destination / "components.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "Collected dependency license notices from build inputs and verified upstream sources"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--vcpkg-share", type=Path, required=True)
    parser.add_argument("--bridge-source", type=Path)
    parser.add_argument("--imgui-source", type=Path)
    parser.add_argument("--implot-source", type=Path)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--distribution", choices=DISTRIBUTIONS, default="combined")
    parser.add_argument("--frontend", type=Path)
    args = parser.parse_args()
    collect(
        args.destination,
        args.vcpkg_share,
        args.bridge_source,
        args.imgui_source,
        args.cache,
        args.implot_source,
        distribution=args.distribution,
        frontend=args.frontend,
    )


if __name__ == "__main__":
    main()
