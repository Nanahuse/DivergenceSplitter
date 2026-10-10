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
        license_expression="MIT",
    )


def staged_runtime(root: Path, *, extra_notice: bool = True) -> Path:
    runtime = root / "build_python_test" / "python"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "python.exe").write_bytes(b"python")
    (runtime / "LICENSE.txt").write_text("CPython license text", encoding="utf-8")
    if extra_notice:
        licenses = runtime / "licenses"
        licenses.mkdir()
        (licenses / "vendor.txt").write_text("runtime vendor notice", encoding="utf-8")
    return runtime


class TestReleaseClosure:
    def test_includes_explicitly_bundled_optional_backend(self) -> None:
        ndi = FakeDistribution("ndi-python", "6.3.2.4", requires=["numpy"])
        numpy = FakeDistribution("numpy", "2.5.2")
        closure = invgen.release_closure(
            installed(ui_distribution(), ndi, numpy),
            additional_roots=("ndi-python",),
        )
        assert set(closure) == {"divergencesplitter-ui", "ndi-python", "numpy"}

    def test_missing_explicit_backend_fails(self) -> None:
        with pytest.raises(RuntimeError, match="ndi-python.*not installed"):
            invgen.release_closure(
                installed(ui_distribution()), additional_roots=("ndi-python",)
            )

    def test_traces_transitive_dependencies(self) -> None:
        runtime = FakeDistribution(
            "divergencesplitter-runtime",
            "0.1.0",
            requires=["core-package"],
            license_expression="MIT",
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
            license_expression="MIT",
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


class TestNdiLicenseBoundary:
    def ndi_distribution(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> FakeDistribution:
        dist = FakeDistribution(
            "ndi-python",
            "6.3.2.4",
            license="MIT",
            license_files={"licenses/LICENSE": "binding MIT text"},
        )
        notice = tmp_path / "NDIlib" / "Processing.NDI.Lib.Licenses.txt"
        notice.parent.mkdir()
        notice.write_text("NDI runtime notices", encoding="utf-8")
        monkeypatch.setattr(dist, "locate_file", lambda path: tmp_path / path)
        return dist

    def test_binding_license_text_excludes_runtime_notices(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dist = self.ndi_distribution(tmp_path, monkeypatch)

        text = invgen.license_text(dist)
        assert "binding MIT text" in text
        assert "NDI runtime notices" not in text

    def test_runtime_notices_stay_outside_dist_info(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dist = self.ndi_distribution(tmp_path, monkeypatch)

        distribution = tmp_path / "distribution"
        monkeypatch.setattr(invgen, "NDI_LICENSE_DOCUMENT_PATH", tmp_path / "NDI.md")
        (tmp_path / "NDI.md").write_text("NDI project notice", encoding="utf-8")
        assets = invgen.ndi_runtime_assets({"ndi-python": dist}, distribution)

        assert [asset["name"] for asset in assets] == [
            invgen.NDI_RUNTIME_ASSET_NAME,
            invgen.NDI_RUNTIME_NOTICES_ASSET_NAME,
        ]
        assert [asset["license"] for asset in assets] == [
            "Licensing Notice",
            "Third-party notices",
        ]
        assert all("version" not in asset for asset in assets)
        assert "NDI SDK License Agreement" not in (
            distribution / assets[0]["license_file"]
        ).read_text(encoding="utf-8")
        assert "NDI runtime notices" in (
            distribution / assets[1]["license_file"]
        ).read_text(encoding="utf-8")

    def test_absent_binding_emits_no_assets(self) -> None:
        assert invgen.ndi_runtime_assets({}, Path(".")) == []


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

    def test_mechanical_text_takes_precedence_over_component_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fallback = tmp_path / "fallback.txt"
        fallback.write_text("fallback text", encoding="utf-8")
        monkeypatch.setitem(
            invgen.LICENSE_TEXT_FALLBACKS,
            "flet",
            invgen.LicenseTextFallback(fallback, "test fallback"),
        )
        dist = FakeDistribution(
            "flet",
            "1.0.0",
            license_expression="Apache-2.0",
            license_files={"licenses/LICENSE": "wheel license text"},
        )

        assert "wheel license text" in invgen.license_text(dist)
        assert "fallback text" not in invgen.license_text(dist)

    def test_fallback_is_component_specific_even_for_same_spdx(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fallback = tmp_path / "fallback.txt"
        fallback.write_text("flet-only text", encoding="utf-8")
        monkeypatch.setitem(
            invgen.LICENSE_TEXT_FALLBACKS,
            "flet",
            invgen.LicenseTextFallback(fallback, "test fallback"),
        )
        flet = FakeDistribution("flet", "1.0.0", license_expression="Apache-2.0")
        another = FakeDistribution("another", "1.0.0", license_expression="Apache-2.0")

        assert invgen.license_text(flet) == "flet-only text"
        with pytest.raises(RuntimeError, match="cannot collect"):
            invgen.license_text(another)

    def test_missing_license_text_without_component_fallback_fails(self) -> None:
        dist = FakeDistribution("mine", "1.0.0", license_expression="MIT")

        with pytest.raises(RuntimeError, match="cannot collect"):
            invgen.license_text(dist)

    def test_mpl_component_carries_source_availability(self) -> None:
        dist = FakeDistribution(
            "certifi",
            "2026.7.22",
            license_expression="MPL-2.0",
            license_files={"LICENSE": "MPL text"},
        )

        text = invgen.license_text(dist)

        assert "=== MPL-2.0 Source Availability ===" in text
        assert "https://pypi.org/project/certifi/2026.7.22/#files" in text

    def test_non_mpl_component_has_no_source_note(self) -> None:
        dist = FakeDistribution(
            "mine",
            "1.0.0",
            license_expression="MIT",
            license_files={"LICENSE": "MIT text"},
        )

        assert "Source Availability" not in invgen.license_text(dist)


class TestBuildInventory:
    def test_packages_are_sorted_by_normalized_name(self, tmp_path: Path) -> None:
        dists = [
            ui_distribution(
                requires=[
                    "numpy",
                    "opencv-contrib-python",
                    "divergencesplitter-runtime",
                ]
            ),
            FakeDistribution(
                "divergencesplitter-runtime",
                "0.1.0",
                license_expression="MIT",
            ),
            FakeDistribution(
                "numpy",
                "2.5.2",
                license_expression="BSD-3-Clause",
                license_files={"licenses/LICENSE.txt": "numpy text"},
            ),
            FakeDistribution(
                "opencv-contrib-python",
                "5.0.0.93",
                license="Apache 2.0",
                license_files={"LICENSE.txt": "opencv text"},
            ),
        ]
        override = invgen.OVERRIDES["opencv-contrib-python"]
        invgen.OVERRIDES["opencv-contrib-python"] = invgen.Override(
            "Apache-2.0", "test override"
        )
        try:
            inventory = invgen.build_inventory(
                invgen.release_closure(installed(*dists)),
                staged_python_runtime=staged_runtime(tmp_path),
                distribution_root=tmp_path,
            )
        finally:
            invgen.OVERRIDES["opencv-contrib-python"] = override

        names = [entry["name"] for entry in inventory["packages"]]

        assert names == sorted(names, key=canonicalize_name)
        assert names == ["numpy", "opencv-contrib-python"]

    def test_package_license_text_is_written_to_its_referenced_file(
        self, tmp_path: Path
    ) -> None:
        dists = [
            ui_distribution(requires=["numpy"]),
            FakeDistribution(
                "numpy",
                "2.5.2",
                license_expression="BSD-3-Clause",
                license_files={"licenses/LICENSE.txt": "numpy text"},
            ),
        ]

        inventory = invgen.build_inventory(
            invgen.release_closure(installed(*dists)),
            staged_python_runtime=staged_runtime(tmp_path),
            distribution_root=tmp_path,
        )

        package_entry = inventory["packages"][0]
        assert package_entry["license_file"] == "licenses/packages/numpy.txt"
        assert "license_text" not in package_entry
        assert (tmp_path / package_entry["license_file"]).read_text(
            encoding="utf-8"
        ) == "=== licenses/LICENSE.txt ===\nnumpy text"
        assert inventory["schema_version"] == 7
        assert (tmp_path / "license_inventory.json").is_file()
        assert (tmp_path / "licenses/CPython.txt").read_text(
            encoding="utf-8"
        ) == "CPython license text"

    def test_own_packages_are_not_licensed_or_displayed(self, tmp_path: Path) -> None:
        dists = [
            ui_distribution(requires=["divergencesplitter-runtime", "numpy"]),
            FakeDistribution(
                "divergencesplitter-runtime",
                "0.1.0",
                requires=["divergencesplitter"],
                license_expression="MIT",
            ),
            FakeDistribution(
                "divergencesplitter",
                "0.1.0",
                license_expression="MIT",
            ),
            FakeDistribution(
                "numpy",
                "2.5.2",
                license_expression="BSD-3-Clause",
                license_files={"licenses/LICENSE.txt": "numpy text"},
            ),
        ]

        inventory = invgen.build_inventory(
            invgen.release_closure(installed(*dists)),
            staged_python_runtime=staged_runtime(tmp_path),
            distribution_root=tmp_path,
        )

        names = [entry["name"] for entry in inventory["packages"]]

        assert names == ["numpy"]

    def test_ndi_runtime_is_assets_not_part_of_binding_license(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ndi = FakeDistribution(
            "ndi-python",
            "6.3.2.4",
            license="MIT",
            license_files={"licenses/LICENSE": "binding MIT text"},
        )
        notice = tmp_path / "NDIlib" / "Processing.NDI.Lib.Licenses.txt"
        notice.parent.mkdir()
        notice.write_text("NDI runtime notices", encoding="utf-8")
        monkeypatch.setattr(ndi, "locate_file", lambda path: tmp_path / path)
        dists = [ui_distribution(requires=["ndi-python"]), ndi]

        monkeypatch.setattr(invgen, "NDI_LICENSE_DOCUMENT_PATH", tmp_path / "NDI.md")
        (tmp_path / "NDI.md").write_text("NDI project notice", encoding="utf-8")
        inventory = invgen.build_inventory(
            invgen.release_closure(installed(*dists)),
            staged_python_runtime=staged_runtime(tmp_path),
            distribution_root=tmp_path,
        )

        binding = next(
            entry for entry in inventory["packages"] if entry["name"] == "ndi-python"
        )
        assert binding["license"] == "MIT"
        assert "license_text" not in binding
        assert [asset["name"] for asset in inventory["assets"]][-2:] == [
            invgen.NDI_RUNTIME_ASSET_NAME,
            invgen.NDI_RUNTIME_NOTICES_ASSET_NAME,
        ]
        ndi_notices = inventory["assets"][-1]["license_file"]
        assert "NDI runtime notices" in (tmp_path / ndi_notices).read_text(
            encoding="utf-8"
        )


class TestApplicationEntry:
    def test_application_is_copied_from_root_license(self, tmp_path: Path) -> None:
        entry = invgen.application_entry(tmp_path)

        assert entry["name"] == "DivergenceSplitter"
        assert entry["license"] == "MIT"
        assert entry["license_file"] == "licenses/application/DivergenceSplitter.txt"
        assert (
            tmp_path / entry["license_file"]
        ).read_bytes() == invgen.APPLICATION_LICENSE_PATH.read_bytes()


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


class TestDistributionGeneration:
    def test_generates_inventory_and_all_referenced_files(self, tmp_path: Path) -> None:
        ui = ui_distribution(requires=["sample-package"])
        sample = FakeDistribution(
            "sample-package",
            "2.3.1",
            license_expression="MIT",
            license_files={"licenses/LICENSE": "sample package terms"},
        )
        inventory = invgen.build_inventory(
            invgen.release_closure(installed(ui, sample)),
            staged_python_runtime=staged_runtime(tmp_path),
            distribution_root=tmp_path,
        )

        saved = json.loads((tmp_path / "license_inventory.json").read_text())
        assert saved == inventory
        assert "license_text" not in json.dumps(inventory)
        assert inventory["packages"][0]["license_file"] == (
            "licenses/packages/sample-package.txt"
        )
        assert (tmp_path / inventory["packages"][0]["license_file"]).read_text() == (
            "=== licenses/LICENSE ===\nsample package terms"
        )

    def test_runtime_assets_come_from_staged_build_outputs(
        self, tmp_path: Path
    ) -> None:
        runtime = staged_runtime(tmp_path)
        inventory = invgen.build_inventory(
            invgen.release_closure(installed(ui_distribution())),
            staged_python_runtime=runtime,
            distribution_root=tmp_path,
        )

        by_name = {asset["name"]: asset for asset in inventory["assets"]}
        cpython = tmp_path / by_name["CPython"]["license_file"]
        runtime_notices = (
            tmp_path
            / by_name["Flet embedded Python runtime third-party notices"][
                "license_file"
            ]
        )
        assert cpython.read_text(encoding="utf-8") == "CPython license text"
        assert "licenses/vendor.txt" in runtime_notices.read_text(encoding="utf-8")

    def test_third_party_notices_use_the_generated_distribution_files(
        self, tmp_path: Path
    ) -> None:
        ui = ui_distribution(requires=["sample-package"])
        sample = FakeDistribution(
            "sample-package",
            "2.3.1",
            license_expression="MIT",
            license_files={"LICENSE": "sample package terms"},
        )
        inventory = invgen.build_inventory(
            invgen.release_closure(installed(ui, sample)),
            staged_python_runtime=staged_runtime(tmp_path),
            distribution_root=tmp_path,
        )
        rendered = invgen.render_third_party_notices(
            inventory, distribution_root=tmp_path
        )

        assert "DivergenceSplitter" in rendered
        assert "sample-package 2.3.1" in rendered
        assert "CPython" in rendered
        assert "dart_bridge" in rendered
        assert "CPython license text" in rendered
        assert "sample package terms" in rendered
        assert "Flutter and Dart dependency notices" in rendered

    def test_missing_generated_license_file_is_a_build_error(
        self, tmp_path: Path
    ) -> None:
        inventory = invgen.build_inventory(
            invgen.release_closure(installed(ui_distribution())),
            staged_python_runtime=staged_runtime(tmp_path),
            distribution_root=tmp_path,
        )
        (tmp_path / inventory["assets"][0]["license_file"]).unlink()

        with pytest.raises(RuntimeError, match="license file was not generated"):
            invgen.validate_inventory_files(inventory, tmp_path)
