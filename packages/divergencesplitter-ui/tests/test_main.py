from __future__ import annotations

from pathlib import Path

from divergencesplitter_ui import main
from divergencesplitter_ui.flet_application import FletApplication


class FakeApplication:
    def __init__(self, configuration: Path | None) -> None:
        self.configuration = configuration
        self.ran = False

    def run(self) -> None:
        self.ran = True


def make_fake(created: list[FakeApplication]):
    def build(configuration: Path | None) -> FakeApplication:
        application = FakeApplication(configuration)
        created.append(application)
        return application

    return build


class TestEntryPoint:
    def test_build_application_uses_the_flet_application(self) -> None:
        application = main.build_application(None)

        assert isinstance(application, FletApplication)

    def test_main_runs_the_flet_application(self, monkeypatch) -> None:
        created: list[FakeApplication] = []
        monkeypatch.setattr(main, "build_application", make_fake(created))

        assert main.main(["config.json"]) == 0

        assert len(created) == 1
        assert created[0].configuration == Path("config.json")
        assert created[0].ran is True

    def test_main_without_configuration(self, monkeypatch) -> None:
        created: list[FakeApplication] = []
        monkeypatch.setattr(main, "build_application", make_fake(created))

        assert main.main([]) == 0

        assert created[0].configuration is None

    def test_usage_error_keeps_its_exit_code(self) -> None:
        assert main.main(["--unknown"]) == 2

    def test_parser_keeps_the_public_program_name(self) -> None:
        assert main.build_parser().prog == "divergencesplitter-ui"
