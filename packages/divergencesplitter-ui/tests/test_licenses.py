from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import divergencesplitter_ui.licenses as license_module
import pytest
from divergencesplitter_ui.licenses import (
    ApplicationLicense,
    AssetLicense,
    LicenseEntry,
    LicenseInventory,
    LicenseInventoryError,
    LicenseSection,
    license_sections,
    load_inventory,
)


def document(
    packages: list[dict[str, Any]],
    *,
    application: dict[str, Any] | None = None,
    assets: list[dict[str, Any]] | None = None,
    schema_version: int = 7,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "application": application
        or {
            "name": "DivergenceSplitter",
            "license": "MIT",
            "license_file": "licenses/application/DivergenceSplitter.txt",
        },
        "packages": packages,
        "assets": assets or [],
    }


def package(**fields: Any) -> dict[str, Any]:
    defaults = {
        "name": "numpy",
        "version": "2.5.2",
        "license": "BSD-3-Clause",
        "license_file": "licenses/packages/numpy.txt",
    }
    defaults.update(fields)
    return defaults


def asset(**fields: Any) -> dict[str, Any]:
    defaults = {
        "name": "sample-asset",
        "version": "1.0",
        "license": "MIT",
        "license_file": "licenses/runtime/sample-asset.txt",
    }
    defaults.update(fields)
    return defaults


def _populate_license_files(inventory: dict[str, Any], root: Path) -> None:
    default_texts = {
        "licenses/application/DivergenceSplitter.txt": "MIT text",
        "licenses/packages/numpy.txt": "full BSD text",
        "licenses/packages/pyyaml.txt": "full BSD text",
        "licenses/runtime/sample-asset.txt": "the asset license text",
    }
    entries = [
        inventory["application"],
        *inventory["packages"],
        *inventory["assets"],
    ]
    for entry in entries:
        reference = entry.get("license_file")
        if (
            not isinstance(reference, str)
            or not reference
            or ".." in Path(reference).parts
        ):
            continue
        target = root / reference
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            default_texts.get(reference, "license body"), encoding="utf-8"
        )


def load(
    packages: list[dict[str, Any]],
    *,
    application: dict[str, Any] | None = None,
    assets: list[dict[str, Any]] | None = None,
    schema_version: int = 7,
) -> LicenseInventory:
    value = document(
        packages,
        schema_version=schema_version,
        application=application,
        assets=assets,
    )
    with TemporaryDirectory() as directory:
        license_root = Path(directory)
        _populate_license_files(value, license_root)
        return load_inventory(StringIO(json.dumps(value)), license_root=license_root)


class TestLoadInventory:
    def test_loads_inventory_and_license_files_beside_packaged_executable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        distribution = tmp_path / "DivergenceSplitter"
        distribution.mkdir()
        executable = distribution / "DivergenceSplitter.exe"
        executable.touch()
        monkeypatch.setattr(license_module.sys, "executable", str(executable))
        inventory = document([package()])
        (distribution / "license_inventory.json").write_text(
            json.dumps(inventory), encoding="utf-8"
        )
        _populate_license_files(inventory, distribution)

        loaded = license_module.bundled_inventory()

        assert loaded.packages[0].license_text == "full BSD text"

    def test_reads_referenced_license_files_into_runtime_entries(self) -> None:
        inventory = load([package(), package(name="pyyaml", license="MIT")])

        assert inventory == LicenseInventory(
            schema_version=7,
            application=ApplicationLicense("DivergenceSplitter", "MIT", "MIT text"),
            packages=(
                LicenseEntry("numpy", "2.5.2", "BSD-3-Clause", "full BSD text"),
                LicenseEntry("pyyaml", "2.5.2", "MIT", "full BSD text"),
            ),
            assets=(),
        )

    def test_decodes_assets_separately_from_packages(self) -> None:
        inventory = load([package()], assets=[asset()])

        assert inventory.assets == (
            AssetLicense("sample-asset", "1.0", "MIT", "the asset license text"),
        )

    def test_asset_version_is_optional(self) -> None:
        unversioned = asset()
        del unversioned["version"]
        inventory = load([], assets=[unversioned])
        assert inventory.assets[0].version is None

    def test_missing_license_file_raises(self, tmp_path: Path) -> None:
        value = document([package()])
        with pytest.raises(LicenseInventoryError, match="license file.*missing"):
            load_inventory(StringIO(json.dumps(value)), license_root=tmp_path)

    def test_invalid_license_file_reference_raises(self, tmp_path: Path) -> None:
        value = document([package(license_file="../outside.txt")])
        app = tmp_path / "licenses" / "application" / "DivergenceSplitter.txt"
        app.parent.mkdir(parents=True)
        app.write_text("application", encoding="utf-8")
        with pytest.raises(LicenseInventoryError, match="invalid license_file"):
            load_inventory(StringIO(json.dumps(value)), license_root=tmp_path)

    def test_missing_asset_field_raises(self) -> None:
        broken = asset()
        del broken["license_file"]
        with pytest.raises(LicenseInventoryError):
            load([], assets=[broken])

    def test_duplicate_asset_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load([], assets=[asset(), asset()])

    def test_missing_assets_list_raises(self) -> None:
        bad = document([])
        del bad["assets"]
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO(json.dumps(bad)), license_root=Path("."))

    def test_preserves_document_order(self) -> None:
        inventory = load([package(name="b"), package(name="a")])

        assert [entry.name for entry in inventory.packages] == ["b", "a"]

    @pytest.mark.parametrize("removed", ["name", "version", "license", "license_file"])
    def test_missing_required_field_raises(self, removed: str) -> None:
        value = package()
        del value[removed]
        with pytest.raises(LicenseInventoryError):
            load([value])

    @pytest.mark.parametrize(
        "package_fields",
        [{"name": ""}, {"version": ""}, {"license": ""}, {"license_file": ""}],
    )
    def test_empty_required_field_raises(self, package_fields: dict[str, Any]) -> None:
        with pytest.raises(LicenseInventoryError):
            load([package(**package_fields)])

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO("{not json"), license_root=Path("."))

    def test_root_must_be_an_object(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO("[]"), license_root=Path("."))

    def test_unsupported_schema_version_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load([], schema_version=1)

    def test_missing_packages_list_raises(self) -> None:
        bad = document([])
        bad["packages"] = "x"
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO(json.dumps(bad)), license_root=Path("."))

    def test_duplicate_package_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load([package(), package()])

    def test_missing_application_section_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(
                StringIO(json.dumps({"schema_version": 7, "packages": []})),
                license_root=Path("."),
            )

    def test_empty_application_field_raises(self) -> None:
        value = document(
            [], application={"name": "", "license": "MIT", "license_file": "a"}
        )
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO(json.dumps(value)), license_root=Path("."))


class TestLicenseSections:
    def make_inventory(self) -> LicenseInventory:
        return LicenseInventory(
            schema_version=7,
            application=ApplicationLicense("DivergenceSplitter", "MIT", "the MIT text"),
            packages=(LicenseEntry("numpy", "2.5.2", "BSD-3-Clause", "the BSD text"),),
            assets=(
                AssetLicense("sample-asset", "1.0", "MIT", "the asset license text"),
            ),
        )

    def test_application_section_comes_first(self) -> None:
        sections = license_sections(self.make_inventory())
        assert sections[0] == LicenseSection("DivergenceSplitter — MIT", "the MIT text")

    def test_every_package_is_a_section(self) -> None:
        sections = license_sections(self.make_inventory())
        assert sections[1] == LicenseSection(
            "numpy 2.5.2 — BSD-3-Clause", "the BSD text"
        )

    def test_every_asset_is_a_section(self) -> None:
        sections = license_sections(self.make_inventory())
        assert sections[2] == LicenseSection(
            "sample-asset 1.0 — MIT", "the asset license text"
        )

    def test_unversioned_asset_title_omits_version(self) -> None:
        inventory = self.make_inventory()
        inventory = LicenseInventory(
            inventory.schema_version,
            inventory.application,
            inventory.packages,
            (
                AssetLicense(
                    "CPython", None, "Python Software Foundation License", "Python text"
                ),
            ),
        )
        assert license_sections(inventory)[2].title == (
            "CPython — Python Software Foundation License"
        )
