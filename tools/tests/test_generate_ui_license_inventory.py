from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from importlib.metadata import Distribution, PackagePath
from pathlib import Path

import generate_ui_license_inventory as invgen
import pytest
from packaging.utils import canonicalize_name


class FakeDistribution(Distribution):
    def __init__(
        self,
        name: str,
        version: str,
        *,
        requires: Iterable[str] = (),
        license_expression: str | None = None,
        license: str | None = None,
        classifiers: Iterable[str] = (),
        license_files: Mapping[str, str] | None = None,
        declared_license_files: Iterable[str] | None = None,
        files: Iterable[str] | None = None,
    ) -> None:
        self._license_files = dict(license_files or {})
        self._file_listing = list(files) if files is not None else None
        fields: list[tuple[str, str]] = [("Name", name), ("Version", version)]
        for requirement in requires:
            fields.append(("Requires-Dist", requirement))
        if license_expression is not None:
            fields.append(("License-Expression", license_expression))
        if license is not None:
            fields.append(("License", license))
        for classifier in classifiers:
            fields.append(("Classifier", classifier))
        declared = (
            list(declared_license_files)
            if declared_license_files is not None
            else list(self._license_files)
        )
        for declared_path in declared:
            fields.append(("License-File", declared_path))
        self._metadata_text = "".join(f"{key}: {value}\n" for key, value in fields)
        self._metadata_text += "\n"

    def read_text(self, filename: str) -> str | None:
        if filename == "METADATA":
            return self._metadata_text
        return self._license_files.get(filename)

    @property
    def files(self) -> list[PackagePath] | None:
        if self._file_listing is None:
            return None
        return [PackagePath(path) for path in self._file_listing]

    def locate_file(self, path: str | os.PathLike[str]) -> Path:
        return Path(path)


def installed(*distributions: FakeDistribution) -> dict[str, Distribution]:
    return {canonicalize_name(dist.metadata["Name"]): dist for dist in distributions}


def ui_distribution(*, requires: Iterable[str] = ()) -> FakeDistribution:
    return FakeDistribution(
        "divergencesplitter-ui",
        "0.1.0",
        requires=requires,
        license_expression="GPL-3.0-only",
    )


class TestReleaseClosure:
    def test_traces_transitive_dependencies(self) -> None:
        runtime = FakeDistribution(
            "divergencesplitter-runtime",
            "0.1.0",
            requires=["core-package"],
            license_expression="GPL-3.0-only",
        )
        core = FakeDistribution(
            "core-package",
            "1.0.0",
            requires=["leaf"],
            license_expression="MIT",
        )
        leaf = FakeDistribution(
            "leaf", "2.0.0", license="MIT", license_files={"LICENSE": "leaf MIT text"}
        )

        closure = invgen.release_closure(
            installed(
                ui_distribution(requires=["divergencesplitter-runtime"]),
                runtime,
                core,
                leaf,
            )
        )

        assert set(closure) == {
            "divergencesplitter-ui",
            "divergencesplitter-runtime",
            "core-package",
            "leaf",
        }

    def test_evaluates_environment_markers_for_windows(self) -> None:
        runtime = FakeDistribution(
            "divergencesplitter-runtime",
            "0.1.0",
            requires=[
                "windows-only; sys_platform == 'win32'",
                "mac-only; sys_platform == 'darwin'",
                "extra-only; extra == 'dev'",
            ],
            license_expression="GPL-3.0-only",
        )
        windows = FakeDistribution(
            "windows-only", "1.0.0", license="MIT", license_files={"LICENSE": "t"}
        )
        mac = FakeDistribution(
            "mac-only", "1.0.0", license="MIT", license_files={"LICENSE": "t"}
        )
        extra = FakeDistribution(
            "extra-only", "1.0.0", license="MIT", license_files={"LICENSE": "t"}
        )

        closure = invgen.release_closure(
            installed(
                ui_distribution(requires=["divergencesplitter-runtime"]),
                runtime,
                windows,
                mac,
                extra,
            )
        )

        assert "windows-only" in closure
        assert "mac-only" not in closure
        assert "extra-only" not in closure

    def test_dev_and_build_dependencies_are_not_included(self) -> None:
        pytest_dist = FakeDistribution(
            "pytest", "9.1.1", license="MIT", license_files={"LICENSE": "t"}
        )
        pyinstaller_dist = FakeDistribution(
            "pyinstaller",
            "6.22.2",
            license="GPL-2.0-or-later",
            license_files={"L": "t"},
        )

        closure = invgen.release_closure(
            installed(ui_distribution(), pytest_dist, pyinstaller_dist)
        )

        assert set(closure) == {"divergencesplitter-ui"}

    def test_missing_requirement_not_installed_raises(self) -> None:
        closure_source = installed(ui_distribution(requires=["missing-package"]))

        with pytest.raises(RuntimeError, match="not installed"):
            invgen.release_closure(closure_source)


class TestLicenseText:
    def test_declared_license_files_are_bundled(self) -> None:
        dist = FakeDistribution(
            "mine",
            "1.0.0",
            license="MIT",
            license_files={"licenses/LICENSE": "the MIT text"},
        )

        assert invgen.license_text(dist) == "=== licenses/LICENSE ===\nthe MIT text"

    def test_license_file_at_dist_info_root_is_found(self) -> None:
        dist = FakeDistribution(
            "mine",
            "1.0.0",
            license="MIT",
            license_files={"LICENSE": "root MIT text"},
        )

        assert invgen.license_text(dist) == "=== LICENSE ===\nroot MIT text"

    def test_multiple_license_files_are_sorted(self) -> None:
        dist = FakeDistribution(
            "mine",
            "1.0.0",
            license_files={
                "licenses/z.txt": "z",
                "licenses/a.txt": "a",
            },
        )

        assert invgen.license_text(dist) == (
            "=== licenses/a.txt ===\na\n\n=== licenses/z.txt ===\nz"
        )

    def test_undisclosed_license_file_is_discovered(self) -> None:
        dist = FakeDistribution(
            "mine",
            "1.0.0",
            declared_license_files=[],
            license_files={"licenses/LICENSE.md": "discovered text"},
            files=["mine-1.0.0.dist-info/licenses/LICENSE.md"],
        )

        assert invgen.license_text(dist) == (
            "=== licenses/LICENSE.md ===\ndiscovered text"
        )

    def test_unreadable_declared_license_file_raises(self) -> None:
        dist = FakeDistribution(
            "mine",
            "1.0.0",
            declared_license_files=["LICENSE.txt"],
            license_files={},
        )

        with pytest.raises(RuntimeError, match="cannot be read"):
            invgen.license_text(dist)

    def test_missing_license_text_raises(self) -> None:
        dist = FakeDistribution("mine", "1.0.0", license="MIT")

        with pytest.raises(RuntimeError, match="cannot collect"):
            invgen.license_text(dist)


class TestBuildInventory:
    def test_packages_are_sorted_by_normalized_name(self) -> None:
        dists = [
            ui_distribution(
                requires=["numpy", "opencv-python", "divergencesplitter-runtime"]
            ),
            FakeDistribution(
                "divergencesplitter-runtime",
                "0.1.0",
                license_expression="GPL-3.0-only",
            ),
            FakeDistribution(
                "numpy",
                "2.5.2",
                license_expression="BSD-3-Clause",
                license_files={"licenses/LICENSE.txt": "numpy text"},
            ),
            FakeDistribution(
                "opencv-python",
                "5.0.0.93",
                license="Apache 2.0",
                license_files={"LICENSE.txt": "opencv text"},
            ),
        ]
        override = invgen.OVERRIDES["opencv-python"]
        invgen.OVERRIDES["opencv-python"] = invgen.Override(
            "Apache-2.0", "test override"
        )
        try:
            inventory = invgen.build_inventory(
                invgen.release_closure(installed(*dists))
            )
        finally:
            invgen.OVERRIDES["opencv-python"] = override

        names = [entry["name"] for entry in inventory["packages"]]

        assert names == sorted(names, key=canonicalize_name)
        assert names == ["numpy", "opencv-python"]

    def test_name_version_license_and_text_are_extracted(self) -> None:
        dists = [
            ui_distribution(requires=["numpy"]),
            FakeDistribution(
                "numpy",
                "2.5.2",
                license_expression="BSD-3-Clause",
                license_files={"licenses/LICENSE.txt": "numpy text"},
            ),
        ]

        inventory = invgen.build_inventory(invgen.release_closure(installed(*dists)))

        assert inventory == {
            "schema_version": 3,
            "application": invgen.application_entry(),
            "packages": [
                {
                    "name": "numpy",
                    "version": "2.5.2",
                    "license": "BSD-3-Clause",
                    "license_text": "=== licenses/LICENSE.txt ===\nnumpy text",
                },
            ],
            "assets": invgen.bundled_assets(),
        }

    def test_bundled_assets_describe_noto_sans_jp(self) -> None:
        assets = invgen.bundled_assets()

        assert len(assets) == 1
        assert assets[0]["name"] == "Noto Sans JP"
        assert assets[0]["license"] == "SIL Open Font License 1.1"
        assert "SIL OPEN FONT LICENSE Version 1.1" in assets[0]["license_text"]

    def test_own_packages_are_not_licensed_or_displayed(self) -> None:
        dists = [
            ui_distribution(requires=["divergencesplitter-runtime", "numpy"]),
            FakeDistribution(
                "divergencesplitter-runtime",
                "0.1.0",
                requires=["divergencesplitter"],
                license_expression="GPL-3.0-only",
            ),
            FakeDistribution(
                "divergencesplitter",
                "0.1.0",
                license_expression="GPL-3.0-only",
            ),
            FakeDistribution(
                "numpy",
                "2.5.2",
                license_expression="BSD-3-Clause",
                license_files={"licenses/LICENSE.txt": "numpy text"},
            ),
        ]

        inventory = invgen.build_inventory(invgen.release_closure(installed(*dists)))

        names = [entry["name"] for entry in inventory["packages"]]

        assert names == ["numpy"]


class TestResolveLicense:
    def test_license_expression_wins(self) -> None:
        dist = FakeDistribution(
            "mine",
            "1.0.0",
            license_expression="BSD-3-Clause",
            license="MIT",
            classifiers=["License :: OSI Approved :: Apache Software License"],
        )

        assert invgen.resolve_license(dist) == "BSD-3-Clause"

    def test_license_field_falls_back_to_expression(self) -> None:
        dist = FakeDistribution("mine", "1.0.0", license="MIT")

        assert invgen.resolve_license(dist) == "MIT"

    def test_ambiguous_classifier_fails_unless_overridden(self) -> None:
        dist = FakeDistribution(
            "mine",
            "1.0.0",
            classifiers=["License :: OSI Approved :: MIT License"],
        )

        with pytest.raises(RuntimeError, match="not an SPDX"):
            invgen.resolve_license(dist)

        invgen.OVERRIDES["mine"] = invgen.Override(
            "MIT", "classifier text is not an SPDX identifier"
        )
        try:
            assert invgen.resolve_license(dist) == "MIT"
        finally:
            del invgen.OVERRIDES["mine"]

    def test_missing_license_metadata_fails(self) -> None:
        dist = FakeDistribution("mine", "1.0.0")

        with pytest.raises(RuntimeError, match="cannot resolve"):
            invgen.resolve_license(dist)

    def test_non_spdx_value_fails_unless_overridden(self) -> None:
        dist = FakeDistribution("mine", "1.0.0", license="Apache 2.0")

        with pytest.raises(RuntimeError, match="not an SPDX"):
            invgen.resolve_license(dist)

        invgen.OVERRIDES["mine"] = invgen.Override(
            "Apache-2.0", "test override for non-SPDX value"
        )
        try:
            assert invgen.resolve_license(dist) == "Apache-2.0"
        finally:
            del invgen.OVERRIDES["mine"]


class TestCheckInventory:
    def make_expected(self) -> invgen.InventoryDocument:
        return {
            "schema_version": 3,
            "application": {
                "name": "DivergenceSplitter",
                "license": "GPL-3.0-only",
                "license_text": "the GPL text",
            },
            "packages": [
                {
                    "name": "dearpygui",
                    "version": "2.3.1",
                    "license": "MIT",
                    "license_text": "dearpygui text",
                },
                {
                    "name": "numpy",
                    "version": "2.5.2",
                    "license": "BSD-3-Clause",
                    "license_text": "numpy text",
                },
            ],
            "assets": [
                {
                    "name": "Noto Sans JP",
                    "license": "SIL Open Font License 1.1",
                    "license_text": "the OFL text",
                },
            ],
        }

    def write_stored(self, tmp_path: Path, document: invgen.InventoryDocument) -> None:
        target = tmp_path / "license_inventory.json"
        target.write_text(json.dumps(document), encoding="utf-8")
        invgen.INVENTORY_PATH = target

    def test_matching_inventory_passes(self, tmp_path: Path) -> None:
        self.write_stored(tmp_path, self.make_expected())

        assert invgen.check_inventory(self.make_expected()) is True

    def test_missing_package_is_detected(self, tmp_path: Path) -> None:
        stored = self.make_expected()
        stored["packages"] = stored["packages"][:1]
        self.write_stored(tmp_path, stored)

        assert invgen.check_inventory(self.make_expected()) is False

    def test_extra_package_is_detected(self, tmp_path: Path) -> None:
        stored = self.make_expected()
        stored["packages"].append(
            {
                "name": "pyzmq",
                "version": "27.2.0",
                "license": "BSD-3-Clause",
                "license_text": "pyzmq text",
            }
        )
        self.write_stored(tmp_path, stored)

        assert invgen.check_inventory(self.make_expected()) is False

    def test_version_difference_is_detected(self, tmp_path: Path) -> None:
        stored = self.make_expected()
        stored["packages"][1]["version"] = "9.9.9"
        self.write_stored(tmp_path, stored)

        assert invgen.check_inventory(self.make_expected()) is False

    def test_license_difference_is_detected(self, tmp_path: Path) -> None:
        stored = self.make_expected()
        stored["packages"][1]["license"] = "Apache-2.0"
        self.write_stored(tmp_path, stored)

        assert invgen.check_inventory(self.make_expected()) is False

    def test_license_text_difference_is_detected(self, tmp_path: Path) -> None:
        stored = self.make_expected()
        stored["packages"][1]["license_text"] = "different text"
        self.write_stored(tmp_path, stored)

        assert invgen.check_inventory(self.make_expected()) is False

    def test_application_difference_is_detected(self, tmp_path: Path) -> None:
        stored = self.make_expected()
        stored["application"]["license_text"] = "edited GPL text"
        self.write_stored(tmp_path, stored)

        assert invgen.check_inventory(self.make_expected()) is False

    def test_missing_asset_is_detected(self, tmp_path: Path) -> None:
        stored = self.make_expected()
        stored["assets"] = []
        self.write_stored(tmp_path, stored)

        assert invgen.check_inventory(self.make_expected()) is False

    def test_missing_inventory_file_fails(self, tmp_path: Path) -> None:
        invgen.INVENTORY_PATH = tmp_path / "absent.json"

        assert invgen.check_inventory(self.make_expected()) is False
