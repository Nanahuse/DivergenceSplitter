from __future__ import annotations

from importlib import metadata

import pytest
from divergencesplitter_ui.about import AboutInfo, about_info


class TestAboutInfo:
    def test_application_name(self, monkeypatch) -> None:
        monkeypatch.setattr(metadata, "version", lambda name: "0.1.0")

        info = about_info()

        assert info.application_name == "DivergenceSplitter"

    def test_version_reads_from_ui_package_metadata(self, monkeypatch) -> None:
        loaded = []

        def fake_version(name: str) -> str:
            loaded.append(name)
            return "0.1.0"

        monkeypatch.setattr(metadata, "version", fake_version)

        info = about_info()

        assert loaded == ["divergencesplitter-ui"]
        assert info.version == "0.1.0"

    def test_returns_exact_info_values(self, monkeypatch) -> None:
        monkeypatch.setattr(metadata, "version", lambda name: "1.2.3")

        assert about_info() == AboutInfo(
            application_name="DivergenceSplitter",
            version="1.2.3",
        )

    def test_missing_metadata_is_reported_not_silently_replaced(
        self, monkeypatch
    ) -> None:
        def missing(name: str) -> str:
            raise metadata.PackageNotFoundError(name)

        monkeypatch.setattr(metadata, "version", missing)

        with pytest.raises(metadata.PackageNotFoundError):
            about_info()
