from __future__ import annotations

from divergencesplitter_ui.about import APPLICATION_NAME, VERSION, AboutInfo, about_info


class TestAboutInfo:
    def test_application_name(self) -> None:
        info = about_info()

        assert info.application_name == APPLICATION_NAME

    def test_returns_generated_version(self) -> None:
        assert about_info() == AboutInfo(
            application_name=APPLICATION_NAME,
            version=VERSION,
        )
