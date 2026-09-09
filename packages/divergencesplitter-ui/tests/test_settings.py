from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from divergencesplitter import LiveSplitConnection
from divergencesplitter_runtime.configuration.json_file import (
    load_configuration,
    save_configuration,
)
from divergencesplitter_runtime.configuration.models import (
    ApplicationConfiguration,
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    InstanceConfiguration,
    RuntimeConfiguration,
    VideoSourceConfiguration,
)
from divergencesplitter_ui.session import SessionState, is_active
from divergencesplitter_ui.settings import (
    CameraDevice,
    EditableCameraSourceConfiguration,
    EditableVideoSourceConfiguration,
    InstanceDraft,
    SettingsModel,
    SourceType,
    camera_source,
    configuration_from_draft,
    draft_from_configuration,
    edit_permission,
    select_configured_camera,
    validate_instances_draft,
)


class FakeCameraEnumerator:
    def __init__(self) -> None:
        self.devices = cast(
            list[CameraDevice],
            [
                SimpleNamespace(
                    backend=SimpleNamespace(name="DIRECT_SHOW"),
                    name="USB Camera",
                    index=7,
                    modes=[],
                )
            ],
        )

    def list_devices(self) -> list[CameraDevice]:
        return self.devices


class EmptyCameraEnumerator:
    def list_devices(self) -> list[CameraDevice]:
        return []


def instance(
    rpc_endpoint: str,
    event_endpoint: str,
    scenario: str,
) -> InstanceConfiguration:
    return InstanceConfiguration(
        LiveSplitConnection(rpc_endpoint, event_endpoint),
        scenario,
    )


def camera_configuration(
    *instances: InstanceConfiguration,
) -> ApplicationConfiguration:
    return ApplicationConfiguration(
        version=1,
        source=CameraSourceConfiguration(
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 2),
            CameraModeConfiguration(1280, 720, 60.0, "MJPG-GUID"),
            False,
        ),
        instances=tuple(instances),
        runtime=RuntimeConfiguration("INFO"),
    )


def video_configuration(
    *instances: InstanceConfiguration,
) -> ApplicationConfiguration:
    return ApplicationConfiguration(
        version=1,
        source=VideoSourceConfiguration("run.mp4"),
        instances=tuple(instances),
        runtime=RuntimeConfiguration("DEBUG"),
    )


def multi_configuration() -> ApplicationConfiguration:
    return video_configuration(
        instance("rpc_1", "event_1", "one.py"),
        instance("rpc_2", "event_2", "two.py"),
        instance("rpc_3", "event_3", "three.py"),
    )


def make_model(
    *,
    configuration: ApplicationConfiguration | None = None,
    path: Path = Path("config.json"),
) -> SettingsModel:
    model = SettingsModel(FakeCameraEnumerator())
    model.open_configuration(
        configuration or camera_configuration(instance("rpc", "event", "scenario.py")),
        path,
    )
    return model


class TestSettingsModel:
    def test_dirty_state_tracks_open_new_edit_and_save(self) -> None:
        model = make_model()
        assert not model.is_dirty

        model.set_log_level("DEBUG")
        assert model.is_dirty
        model.set_log_level("INFO")
        assert model.is_dirty

        model.mark_saved()
        assert not model.is_dirty
        model.set_log_level("INFO")
        assert not model.is_dirty

    def test_new_default_configuration_is_dirty(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())
        draft = model.create_default_camera_configuration(
            Path("new.json"),
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 7),
        )

        assert draft.configuration_path == Path("new.json")
        assert model.is_dirty

    def test_default_camera_configuration_has_no_scenario_instances(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())
        device = CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 7)
        mode = CameraModeConfiguration(1280, 720, 60.0, "MJPG-GUID")

        draft = model.create_default_camera_configuration(
            Path("config.json"), device, mode
        )

        assert draft.configuration_path == Path("config.json")
        assert draft.instances == ()
        assert camera_source(draft) is not None

    def test_edits_one_shared_camera_draft(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())
        path = Path("config.json")
        opened = model.open_configuration(
            camera_configuration(instance("rpc", "event", "scenario.py")),
            path,
        )

        assert model.draft is opened
        assert next(iter(model.list_cameras())).index == 7

        model.set_instance_scenario(0, "next.py")
        model.set_camera_device(CameraBackend.DIRECT_SHOW, "USB Camera", 7)
        model.set_camera_mode(CameraModeConfiguration(1920, 1080, 59.94, "MJPG-GUID"))
        model.set_log_level("DEBUG")

        configuration = model.configuration()
        assert configuration is not None
        assert configuration.instances[0].scenario == "next.py"
        assert configuration.runtime.log_level == "DEBUG"
        assert configuration.source == CameraSourceConfiguration(
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 7),
            CameraModeConfiguration(1920, 1080, 59.94, "MJPG-GUID"),
            False,
        )

    def test_video_source_is_preserved_by_camera_edits(self) -> None:
        configuration = video_configuration(
            instance("rpc", "event", "scenario.py"),
        )
        model = SettingsModel(FakeCameraEnumerator())
        draft = model.open_configuration(configuration, Path("config.json"))

        assert camera_source(draft) is None
        model.set_camera_device(CameraBackend.DIRECT_SHOW, "USB Camera", 7)
        model.set_camera_mode(CameraModeConfiguration(1920, 1080, 60.0, "MJPG-GUID"))

        saved = model.configuration()
        assert saved is not None
        assert saved.source == VideoSourceConfiguration("run.mp4")

    def test_source_switch_preserves_both_editors(self) -> None:
        model = make_model()
        model.set_request_60_fps(True)
        model.set_source_type(SourceType.VIDEO)
        model.set_video_path("clip.mp4")
        model.set_source_type(SourceType.CAMERA)

        assert model.draft is not None
        assert model.draft.source.video.path == "clip.mp4"
        assert model.draft.source.camera.request_60_fps
        assert model.configuration() is not None
        model.set_source_type(SourceType.VIDEO)
        configuration = model.configuration()
        assert configuration is not None
        assert configuration.source == VideoSourceConfiguration("clip.mp4")

    def test_new_configuration_without_camera_can_become_video(self) -> None:
        model = SettingsModel(EmptyCameraEnumerator())
        model.create_default_configuration(Path("new.json"))
        model.set_source_type(SourceType.VIDEO)
        model.set_video_path("clip.mp4")
        model.add_instance()
        model.set_instance_rpc_endpoint(0, "rpc")
        model.set_instance_event_endpoint(0, "event")
        model.set_instance_scenario(0, "scenario.py")

        configuration = model.configuration()
        assert configuration is not None
        assert configuration.source == VideoSourceConfiguration("clip.mp4")


class TestConfigurationProjection:
    def test_single_instance_projects_to_one_draft(self) -> None:
        configuration = video_configuration(
            instance("rpc", "event", "scenario.py"),
        )

        draft = draft_from_configuration(configuration, Path("config.json"))

        assert draft.instances == (InstanceDraft("rpc", "event", "scenario.py"),)
        assert draft.log_level == "DEBUG"
        assert draft.source.selected_type is SourceType.VIDEO
        assert draft.source.video == EditableVideoSourceConfiguration("run.mp4")
        assert draft.source.camera == EditableCameraSourceConfiguration(
            None, None, False
        )

    def test_every_instance_projects_with_order_and_values(self) -> None:
        configuration = video_configuration(
            instance("rpc_a", "event_a", "a.py"),
            instance("rpc_b", "event_b", "b.yaml"),
            instance("rpc_c", "event_c", "c.yml"),
        )

        draft = draft_from_configuration(configuration, Path("config.json"))

        assert draft.instances == (
            InstanceDraft("rpc_a", "event_a", "a.py"),
            InstanceDraft("rpc_b", "event_b", "b.yaml"),
            InstanceDraft("rpc_c", "event_c", "c.yml"),
        )

    def test_empty_instances_project_to_empty_draft(self) -> None:
        draft = draft_from_configuration(video_configuration(), Path("config.json"))

        assert draft.instances == ()

    def test_draft_back_to_configuration_keeps_pairs_and_order(self) -> None:
        configuration = video_configuration(
            instance("rpc_a", "event_a", "a.py"),
            instance("rpc_b", "event_b", "b.yaml"),
        )
        draft = draft_from_configuration(configuration, Path("config.json"))

        rebuilt = configuration_from_draft(draft)

        assert rebuilt == ApplicationConfiguration(
            version=1,
            source=VideoSourceConfiguration("run.mp4"),
            instances=(
                InstanceConfiguration(
                    LiveSplitConnection("rpc_a", "event_a"),
                    "a.py",
                ),
                InstanceConfiguration(
                    LiveSplitConnection("rpc_b", "event_b"),
                    "b.yaml",
                ),
            ),
            runtime=RuntimeConfiguration("DEBUG"),
        )


class TestInstanceEditing:
    def test_set_scenario_changes_only_target(self) -> None:
        model = make_model(configuration=multi_configuration())

        draft = model.set_instance_scenario(1, "changed.py")

        assert draft is not None
        assert draft.instances[1].scenario == "changed.py"
        assert draft.instances[0] == InstanceDraft("rpc_1", "event_1", "one.py")
        assert draft.instances[2] == InstanceDraft("rpc_3", "event_3", "three.py")

    def test_set_rpc_endpoint_changes_only_target(self) -> None:
        model = make_model(configuration=multi_configuration())

        draft = model.set_instance_rpc_endpoint(1, "tcp://127.0.0.1:54100")

        assert draft is not None
        assert draft.instances[1].rpc_endpoint == "tcp://127.0.0.1:54100"
        assert draft.instances[0] == InstanceDraft("rpc_1", "event_1", "one.py")
        assert draft.instances[2] == InstanceDraft("rpc_3", "event_3", "three.py")

    def test_set_event_endpoint_changes_only_target(self) -> None:
        model = make_model(configuration=multi_configuration())

        draft = model.set_instance_event_endpoint(1, "tcp://127.0.0.1:54101")

        assert draft is not None
        assert draft.instances[1].event_endpoint == "tcp://127.0.0.1:54101"
        assert draft.instances[0] == InstanceDraft("rpc_1", "event_1", "one.py")
        assert draft.instances[2] == InstanceDraft("rpc_3", "event_3", "three.py")

    def test_out_of_range_edit_leaves_draft_unchanged(self) -> None:
        model = make_model()

        assert model.set_instance_scenario(3, "ignored.py") is model.draft
        assert model.set_instance_rpc_endpoint(-1, "ignored") is model.draft
        assert model.set_instance_event_endpoint(1, "ignored") is model.draft


class TestAddInstance:
    def test_appends_empty_instance_to_end(self) -> None:
        model = make_model(configuration=multi_configuration())

        model.add_instance()

        assert model.draft is not None
        assert len(model.draft.instances) == 4
        assert model.draft.instances[:-1] == (
            InstanceDraft("rpc_1", "event_1", "one.py"),
            InstanceDraft("rpc_2", "event_2", "two.py"),
            InstanceDraft("rpc_3", "event_3", "three.py"),
        )
        assert model.draft.instances[-1] == InstanceDraft("", "", "")

    def test_consecutive_adds_append_in_sequence(self) -> None:
        model = make_model(configuration=multi_configuration())

        model.add_instance()
        model.add_instance()

        assert model.draft is not None
        assert tuple(entry.scenario for entry in model.draft.instances) == (
            "one.py",
            "two.py",
            "three.py",
            "",
            "",
        )


class TestRemoveInstance:
    def test_removes_only_target_and_keeps_order(self) -> None:
        model = make_model(configuration=multi_configuration())

        model.remove_instance(1)

        assert model.draft is not None
        assert model.draft.instances == (
            InstanceDraft("rpc_1", "event_1", "one.py"),
            InstanceDraft("rpc_3", "event_3", "three.py"),
        )

    def test_can_remove_first(self) -> None:
        model = make_model(configuration=multi_configuration())

        model.remove_instance(0)

        assert model.draft is not None
        assert tuple(entry.scenario for entry in model.draft.instances) == (
            "two.py",
            "three.py",
        )

    def test_can_remove_last(self) -> None:
        model = make_model(configuration=multi_configuration())

        model.remove_instance(2)

        assert model.draft is not None
        assert tuple(entry.scenario for entry in model.draft.instances) == (
            "one.py",
            "two.py",
        )

    def test_can_remove_down_to_zero_instances(self) -> None:
        model = make_model()

        model.remove_instance(0)

        assert model.draft is not None
        assert model.draft.instances == ()

    def test_out_of_range_remove_leaves_draft_unchanged(self) -> None:
        model = make_model()

        assert model.remove_instance(1) is model.draft


class TestInstanceValidation:
    def test_zero_instances_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one instance is required"):
            validate_instances_draft(())

    @pytest.mark.parametrize("scenario", ["", "   ", "\t\n"])
    def test_empty_scenario_is_rejected(self, scenario: str) -> None:
        with pytest.raises(ValueError, match="has an empty scenario"):
            validate_instances_draft((InstanceDraft("rpc", "event", scenario),))

    @pytest.mark.parametrize("endpoint", ["", "   "])
    def test_empty_rpc_endpoint_is_rejected(self, endpoint: str) -> None:
        with pytest.raises(ValueError, match="has an empty RPC endpoint"):
            validate_instances_draft((InstanceDraft(endpoint, "event", "s.py"),))

    @pytest.mark.parametrize("endpoint", ["", "   "])
    def test_empty_event_endpoint_is_rejected(self, endpoint: str) -> None:
        with pytest.raises(ValueError, match="has an empty event endpoint"):
            validate_instances_draft((InstanceDraft("rpc", endpoint, "s.py"),))

    def test_duplicate_rpc_endpoint_is_rejected_with_owner(self) -> None:
        with pytest.raises(
            ValueError,
            match="Instance 2 uses the same RPC endpoint as Instance 1.",
        ):
            validate_instances_draft(
                (
                    InstanceDraft("tcp://127.0.0.1:54000", "event_1", "a.py"),
                    InstanceDraft("tcp://127.0.0.1:54000", "event_2", "b.py"),
                )
            )

    def test_duplicate_event_endpoint_is_rejected_with_owner(self) -> None:
        with pytest.raises(
            ValueError,
            match="Instance 2 uses the same event endpoint as Instance 1.",
        ):
            validate_instances_draft(
                (
                    InstanceDraft("rpc_1", "tcp://127.0.0.1:54001", "a.py"),
                    InstanceDraft("rpc_2", "tcp://127.0.0.1:54001", "b.py"),
                )
            )

    def test_valid_multiple_instances_are_accepted(self) -> None:
        validate_instances_draft(
            (
                InstanceDraft("tcp://127.0.0.1:54000", "tcp://127.0.0.1:54001", "a.py"),
                InstanceDraft(
                    "tcp://127.0.0.1:54002", "tcp://127.0.0.1:54003", "b.yaml"
                ),
            )
        )


class TestRoundTrip:
    def test_configuration_draft_configuration_preserves_instances(self) -> None:
        configuration = video_configuration(
            instance("rpc_1", "event_1", "one.py"),
            instance("rpc_2", "event_2", "two.yaml"),
        )

        draft = draft_from_configuration(configuration, Path("config.json"))
        rebuilt = configuration_from_draft(draft)

        assert rebuilt == configuration

    def test_json_draft_save_json_load_preserves_instances(
        self,
        tmp_path,
    ) -> None:
        path = tmp_path / "config.json"
        configuration = multi_configuration()
        save_configuration(path, configuration)

        draft = draft_from_configuration(load_configuration(path), path)
        save_configuration(path, configuration_from_draft(draft))

        assert load_configuration(path) == configuration


class TestScenarioExtensions:
    def test_scenario_formats_save_independently_per_instance(self) -> None:
        model = make_model()
        model.add_instance()
        model.add_instance()
        model.set_instance_scenario(0, "scenario_a.py")
        model.set_instance_scenario(1, "scenario_b.yaml")
        model.set_instance_scenario(2, "scenario_c.yml")
        model.set_instance_rpc_endpoint(1, "rpc_2")
        model.set_instance_event_endpoint(1, "event_2")
        model.set_instance_rpc_endpoint(2, "rpc_3")
        model.set_instance_event_endpoint(2, "event_3")

        configuration = model.configuration()

        assert configuration is not None
        assert tuple(entry.scenario for entry in configuration.instances) == (
            "scenario_a.py",
            "scenario_b.yaml",
            "scenario_c.yml",
        )


class TestCameraSelection:
    def test_unique_name_uses_current_id(self) -> None:
        devices = cast(
            list[CameraDevice],
            [
                SimpleNamespace(
                    backend=SimpleNamespace(name="DIRECT_SHOW"),
                    name="USB Camera",
                    index=7,
                    modes=[],
                )
            ],
        )

        selected = select_configured_camera(
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 2),
            devices,
        )

        assert selected is devices[0]

    def test_duplicate_name_uses_saved_id(self) -> None:
        devices = cast(
            list[CameraDevice],
            [
                SimpleNamespace(
                    backend=SimpleNamespace(name="DIRECT_SHOW"),
                    name="USB Camera",
                    index=1,
                    modes=[],
                ),
                SimpleNamespace(
                    backend=SimpleNamespace(name="DIRECT_SHOW"),
                    name="USB Camera",
                    index=2,
                    modes=[],
                ),
            ],
        )

        selected = select_configured_camera(
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 2),
            devices,
        )

        assert selected is devices[1]

    def test_unresolved_duplicate_requires_reselection(self) -> None:
        devices = cast(
            list[CameraDevice],
            [
                SimpleNamespace(
                    backend=SimpleNamespace(name="DIRECT_SHOW"),
                    name="USB Camera",
                    index=1,
                    modes=[],
                ),
                SimpleNamespace(
                    backend=SimpleNamespace(name="DIRECT_SHOW"),
                    name="USB Camera",
                    index=3,
                    modes=[],
                ),
            ],
        )

        assert (
            select_configured_camera(
                CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 2),
                devices,
            )
            is None
        )


class TestSettingsDecisions:
    def test_running_session_keeps_draft_editable(self) -> None:
        permission = edit_permission(SessionState.RUNNING)

        assert permission.source
        assert permission.instances
        assert permission.log_level

    def test_idle_session_allows_all_edits(self) -> None:
        permission = edit_permission(SessionState.IDLE)

        assert permission.source
        assert permission.instances
        assert permission.log_level

    def test_transition_session_disables_all_configuration_edits(self) -> None:
        permission = edit_permission(SessionState.STOPPING)

        assert not permission.source
        assert not permission.instances
        assert not permission.log_level

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
