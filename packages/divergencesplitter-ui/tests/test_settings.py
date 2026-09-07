from pathlib import Path
from types import SimpleNamespace
from typing import cast

from divergencesplitter import LiveSplitConnection
from divergencesplitter_runtime.configuration.models import (
    ApplicationConfiguration,
    CameraDeviceConfiguration,
    CameraSourceConfiguration,
    InstanceConfiguration,
    RuntimeConfiguration,
    VideoSourceConfiguration,
)
from divergencesplitter_ui.session import SessionState, is_active
from divergencesplitter_ui.settings import (
    CameraDevice,
    SaveDecision,
    SettingsModel,
    camera_source,
    edit_permission,
    parse_camera_dimensions,
    save_decision,
    select_configured_camera,
)


class FakeCameraEnumerator:
    def __init__(self) -> None:
        self.devices = cast(
            list[CameraDevice],
            [SimpleNamespace(name="USB Camera", id=7)],
        )

    def list_devices(self) -> list[CameraDevice]:
        return self.devices


def camera_configuration() -> ApplicationConfiguration:
    return ApplicationConfiguration(
        version=1,
        source=CameraSourceConfiguration(
            CameraDeviceConfiguration("USB Camera", 2),
            width=1280,
            height=720,
            fps=60.0,
        ),
        instances=(
            InstanceConfiguration(
                LiveSplitConnection("rpc", "event"),
                "scenario.py",
            ),
        ),
        runtime=RuntimeConfiguration("INFO"),
    )


class TestSettingsModel:
    def test_edits_one_shared_camera_draft(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())
        path = Path("config.json")
        opened = model.open_configuration(camera_configuration(), path)

        assert model.draft is opened
        assert next(iter(model.list_cameras())).id == 7

        model.set_scenario_script("next.py")
        model.set_camera_device("USB Camera", 7)
        model.set_camera_dimensions(1920, 1080, 59.94)
        model.set_log_level("DEBUG")

        configuration = model.configuration()
        assert configuration is not None
        assert configuration.instances[0].scenario == "next.py"
        assert configuration.runtime.log_level == "DEBUG"
        assert configuration.source == CameraSourceConfiguration(
            CameraDeviceConfiguration("USB Camera", 7),
            width=1920,
            height=1080,
            fps=59.94,
        )

    def test_video_source_is_preserved_by_camera_edits(self) -> None:
        configuration = ApplicationConfiguration(
            version=1,
            source=VideoSourceConfiguration("run.mp4"),
            instances=(
                InstanceConfiguration(
                    LiveSplitConnection("rpc", "event"),
                    "scenario.py",
                ),
            ),
            runtime=RuntimeConfiguration("INFO"),
        )
        model = SettingsModel(FakeCameraEnumerator())
        draft = model.open_configuration(configuration, Path("config.json"))

        assert camera_source(draft) is None
        model.set_camera_device("USB Camera", 7)
        model.set_camera_dimensions(1920, 1080, 60.0)

        saved = model.configuration()
        assert saved is not None
        assert saved.source == VideoSourceConfiguration("run.mp4")


class TestCameraSelection:
    def test_unique_name_uses_current_id(self) -> None:
        devices = cast(
            list[CameraDevice],
            [SimpleNamespace(name="USB Camera", id=7)],
        )

        selected = select_configured_camera(
            CameraDeviceConfiguration("USB Camera", 2),
            devices,
        )

        assert selected is devices[0]

    def test_duplicate_name_uses_saved_id(self) -> None:
        devices = cast(
            list[CameraDevice],
            [
                SimpleNamespace(name="USB Camera", id=1),
                SimpleNamespace(name="USB Camera", id=2),
            ],
        )

        selected = select_configured_camera(
            CameraDeviceConfiguration("USB Camera", 2),
            devices,
        )

        assert selected is devices[1]

    def test_unresolved_duplicate_requires_reselection(self) -> None:
        devices = cast(
            list[CameraDevice],
            [
                SimpleNamespace(name="USB Camera", id=1),
                SimpleNamespace(name="USB Camera", id=3),
            ],
        )

        assert (
            select_configured_camera(
                CameraDeviceConfiguration("USB Camera", 2),
                devices,
            )
            is None
        )


class TestSettingsDecisions:
    def test_active_session_disables_source_and_scenario_only(self) -> None:
        permission = edit_permission(active=True)

        assert not permission.source
        assert not permission.scenario
        assert permission.log_level

    def test_save_starts_only_without_active_session(self) -> None:
        assert save_decision(active=False) == SaveDecision(
            start=True,
            reflect_log_level=False,
        )
        assert save_decision(active=True) == SaveDecision(
            start=False,
            reflect_log_level=True,
        )

    def test_session_activity_matches_in_progress_states(self) -> None:
        for state in (
            SessionState.LOADING,
            SessionState.CONNECTING,
            SessionState.RUNNING,
            SessionState.STOPPING,
        ):
            assert is_active(state)
        for state in (
            SessionState.IDLE,
            SessionState.COMPLETED,
            SessionState.FAILED,
            SessionState.STOPPED,
        ):
            assert not is_active(state)

    def test_camera_dimensions_are_parsed_from_widget_values(self) -> None:
        dimensions = parse_camera_dimensions("1920", "1080", "59.94")

        assert dimensions.width == 1920
        assert dimensions.height == 1080
        assert dimensions.fps == 59.94
