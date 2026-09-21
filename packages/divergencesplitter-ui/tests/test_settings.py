from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from divergencesplitter import LiveSplitConnection
from divergencesplitter_runtime.configuration.app_settings_json import (
    load_app_settings,
    save_app_settings,
)
from divergencesplitter_runtime.configuration.models import (
    AppSettings,
    CameraBackend,
    CameraDeviceConfiguration,
    CameraModeConfiguration,
    CameraSourceConfiguration,
    InstanceConfiguration,
    NdiSourceConfiguration,
    Profile,
    ResizeConfiguration,
    Theme,
    UiSettings,
    VideoSourceConfiguration,
)
from divergencesplitter_ui.session import SessionState, is_active
from divergencesplitter_ui.settings import (
    SOURCE_TYPE_LABELS,
    AppSettingsDraft,
    CameraDevice,
    CameraMode,
    EditableCameraSourceConfiguration,
    EditableCropConfiguration,
    EditableInstanceConfiguration,
    EditableNdiSourceConfiguration,
    EditableResizeConfiguration,
    EditableVideoSourceConfiguration,
    SettingsModel,
    SourceType,
    camera_mode_label,
    camera_source,
    edit_permission,
    editable_profile_from,
    ndi_source,
    profile_from_editable,
    select_configured_camera,
    validate_instances_draft,
)

BASE = Path.cwd()


def p(name: str) -> str:
    """Return an absolute path string for a profile-owned file."""

    return str(BASE / name)


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


def camera_profile(
    *instances: InstanceConfiguration,
) -> Profile:
    return Profile(
        version=1,
        source=CameraSourceConfiguration(
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 2),
            CameraModeConfiguration(1280, 720, 60.0, "MJPG-GUID"),
            False,
        ),
        instances=tuple(instances),
    )


def video_profile(
    *instances: InstanceConfiguration,
) -> Profile:
    return Profile(
        version=1,
        source=VideoSourceConfiguration(p("run.mp4")),
        instances=tuple(instances),
    )


def ndi_profile(
    *instances: InstanceConfiguration,
) -> Profile:
    return Profile(
        version=1,
        source=NdiSourceConfiguration("Gaming PC (OBS)"),
        instances=tuple(instances),
    )


def multi_profile() -> Profile:
    return video_profile(
        instance("rpc_1", "event_1", p("one.py")),
        instance("rpc_2", "event_2", p("two.py")),
        instance("rpc_3", "event_3", p("three.py")),
    )


def make_model(
    *,
    profile: Profile | None = None,
    path: Path = Path("config.json"),
) -> SettingsModel:
    model = SettingsModel(FakeCameraEnumerator())
    model.open_profile(
        profile or camera_profile(instance("rpc", "event", p("scenario.py"))),
        path,
    )
    return model


class TestSettingsModel:
    def test_dirty_state_tracks_open_edit_and_save(self) -> None:
        model = make_model()
        assert not model.is_dirty

        model.set_instance_scenario(0, p("next.py"))
        assert model.is_dirty

        model.mark_saved()
        assert not model.is_dirty

    def test_log_level_does_not_dirty_the_profile(self) -> None:
        model = make_model()
        model.mark_saved()
        assert not model.is_dirty

        model.edit_log_level("DEBUG")

        assert not model.is_dirty
        assert model.app_settings_draft.log_level == "DEBUG"
        assert model.validate_app_settings().log_level == "DEBUG"

    def test_reaction_time_does_not_dirty_the_profile(self) -> None:
        model = make_model()
        model.mark_saved()

        model.edit_reaction_time("30")

        assert not model.is_dirty
        assert model.app_settings_draft.reaction_time_text == "30"
        assert model.validate_app_settings().reaction_time_ms == 30

    def test_new_default_profile_is_dirty(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())
        draft = model.create_default_camera_profile(
            Path("new.json"),
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 7),
        )

        assert draft.profile_path == Path("new.json")
        assert model.is_dirty

    def test_default_camera_profile_has_no_scenario_instances(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())
        device = CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 7)
        mode = CameraModeConfiguration(1280, 720, 60.0, "MJPG-GUID")

        draft = model.create_default_camera_profile(Path("config.json"), device, mode)

        assert draft.profile_path == Path("config.json")
        assert draft.instances == ()
        assert camera_source(draft) is not None

    def test_edits_one_shared_camera_draft(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())
        path = Path("config.json")
        opened = model.open_profile(
            camera_profile(instance("rpc", "event", p("scenario.py"))),
            path,
        )

        assert model.draft is opened
        assert next(iter(model.list_cameras())).index == 7

        model.set_instance_scenario(0, p("next.py"))
        model.set_camera_device(CameraBackend.DIRECT_SHOW, "USB Camera", 7)
        model.set_camera_mode(CameraModeConfiguration(1920, 1080, 59.94, "MJPG-GUID"))
        model.edit_log_level("DEBUG")

        configuration = model.profile_document()
        assert configuration is not None
        assert configuration.instances[0].scenario == p("next.py")
        assert configuration.source == CameraSourceConfiguration(
            CameraDeviceConfiguration(CameraBackend.DIRECT_SHOW, "USB Camera", 7),
            CameraModeConfiguration(1920, 1080, 59.94, "MJPG-GUID"),
            False,
        )

    def test_video_source_is_preserved_by_camera_edits(self) -> None:
        configuration = video_profile(
            instance("rpc", "event", p("scenario.py")),
        )
        model = SettingsModel(FakeCameraEnumerator())
        draft = model.open_profile(configuration, Path("config.json"))

        assert camera_source(draft) is None
        model.set_camera_device(CameraBackend.DIRECT_SHOW, "USB Camera", 7)
        model.set_camera_mode(CameraModeConfiguration(1920, 1080, 60.0, "MJPG-GUID"))

        saved = model.profile_document()
        assert saved is not None
        assert saved.source == VideoSourceConfiguration(p("run.mp4"))

    def test_source_switch_preserves_both_editors(self) -> None:
        model = make_model()
        model.set_request_60_fps(True)
        model.set_source_type(SourceType.VIDEO)
        model.set_video_path(p("clip.mp4"))
        model.set_source_type(SourceType.CAMERA)

        assert model.draft is not None
        assert model.draft.source.video.path == p("clip.mp4")
        assert model.draft.source.camera.request_60_fps
        assert model.profile_document() is not None
        model.set_source_type(SourceType.VIDEO)
        configuration = model.profile_document()
        assert configuration is not None
        assert configuration.source == VideoSourceConfiguration(p("clip.mp4"))

    def test_source_transform_is_shared_across_source_types_and_dirty(self) -> None:
        model = make_model()
        model.set_crop_values(10, 20, 30, 40)
        model.set_resize_values(320, 240)

        assert model.draft is not None
        assert model.draft.source.transform.crop == EditableCropConfiguration(
            10, 20, 30, 40
        )
        assert model.draft.source.transform.resize == EditableResizeConfiguration(
            320, 240
        )
        model.set_source_type(SourceType.VIDEO)
        model.set_video_path(p("clip.mp4"))
        configuration = model.profile_document()
        assert configuration is not None
        assert configuration.source.transform.resize == ResizeConfiguration(320, 240)

    def test_new_configuration_without_camera_can_become_video(self) -> None:
        model = SettingsModel(EmptyCameraEnumerator())
        model.create_default_profile(Path("new.json"))
        model.set_source_type(SourceType.VIDEO)
        model.set_video_path(p("clip.mp4"))
        model.add_instance()
        model.set_instance_rpc_endpoint(0, "rpc")
        model.set_instance_event_endpoint(0, "event")
        model.set_instance_scenario(0, p("scenario.py"))

        configuration = model.profile_document()
        assert configuration is not None
        assert configuration.source == VideoSourceConfiguration(p("clip.mp4"))


class TestNdiSource:
    def test_source_type_ndi_is_available(self) -> None:
        assert SourceType.NDI == "ndi"
        assert SOURCE_TYPE_LABELS[SourceType.NDI] == "NDI"

    def test_ndi_profile_projects_to_editable(self) -> None:
        draft = editable_profile_from(ndi_profile(), Path("config.json"))

        assert draft.source.selected_type is SourceType.NDI
        assert draft.source.ndi == EditableNdiSourceConfiguration("Gaming PC (OBS)")
        assert ndi_source(draft) is draft.source.ndi
        assert camera_source(draft) is None

    def test_editable_ndi_projects_back_to_profile(self) -> None:
        configuration = ndi_profile(instance("rpc", "event", p("s.py")))
        draft = editable_profile_from(configuration, Path("config.json"))

        rebuilt = profile_from_editable(draft)

        assert rebuilt.source == NdiSourceConfiguration("Gaming PC (OBS)")
        assert rebuilt == configuration

    def test_switch_between_ndi_camera_and_video(self) -> None:
        model = make_model()
        model.set_ndi_available(True)

        model.set_source_type(SourceType.NDI)
        model.set_ndi_source_name("Gaming PC (OBS)")
        configuration = model.profile_document()
        assert configuration is not None
        assert configuration.source == NdiSourceConfiguration("Gaming PC (OBS)")

        model.set_source_type(SourceType.CAMERA)
        configuration = model.profile_document()
        assert configuration is not None
        assert isinstance(configuration.source, CameraSourceConfiguration)

        model.set_source_type(SourceType.VIDEO)
        model.set_video_path(p("clip.mp4"))
        configuration = model.profile_document()
        assert configuration is not None
        assert configuration.source == VideoSourceConfiguration(p("clip.mp4"))

        model.set_source_type(SourceType.NDI)
        configuration = model.profile_document()
        assert configuration is not None
        assert configuration.source == NdiSourceConfiguration("Gaming PC (OBS)")

    def test_ndi_name_is_preserved_across_type_switches(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())
        model.set_ndi_available(True)
        draft = model.open_profile(ndi_profile(), Path("config.json"))

        model.set_source_type(SourceType.VIDEO)
        model.set_source_type(SourceType.NDI)

        assert draft.source.ndi.name == "Gaming PC (OBS)"

    def test_ndi_cannot_be_selected_when_unavailable(self) -> None:
        model = make_model()
        model.set_ndi_available(False)

        assert model.set_source_type(SourceType.NDI) is None
        assert model.draft is not None
        assert model.draft.source.selected_type is SourceType.CAMERA

    def test_ndi_config_opens_when_unavailable_and_can_change(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())
        model.set_ndi_available(False)

        draft = model.open_profile(
            ndi_profile(instance("rpc", "event", p("s.py"))),
            Path("config.json"),
        )

        assert draft.source.selected_type is SourceType.NDI
        assert draft.source.ndi.name == "Gaming PC (OBS)"
        assert model.set_source_type(SourceType.VIDEO) is not None
        assert draft.source.selected_type is SourceType.VIDEO
        assert draft.source.ndi.name == "Gaming PC (OBS)"

    def test_ndi_name_edit_marks_dirty(self) -> None:
        model = make_model()
        model.set_ndi_available(True)
        model.set_source_type(SourceType.NDI)
        model.mark_saved()
        assert not model.is_dirty

        model.set_ndi_source_name("Other Source")

        assert model.is_dirty
        assert model.draft is not None
        assert model.draft.source.ndi.name == "Other Source"

    def test_empty_ndi_name_is_rejected_on_projection(self) -> None:
        model = make_model()
        model.set_ndi_available(True)
        model.set_source_type(SourceType.NDI)
        model.set_ndi_source_name("")

        with pytest.raises(ValueError, match="NDI source must be selected"):
            model.profile_document()


class TestProfileProjection:
    def test_single_instance_projects_to_one_draft(self) -> None:
        configuration = video_profile(
            instance("rpc", "event", p("scenario.py")),
        )

        draft = editable_profile_from(configuration, Path("config.json"))

        assert draft.instances == (
            EditableInstanceConfiguration("rpc", "event", p("scenario.py")),
        )
        assert draft.source.selected_type is SourceType.VIDEO
        assert draft.source.video == EditableVideoSourceConfiguration(p("run.mp4"))
        assert draft.source.camera == EditableCameraSourceConfiguration(
            None, None, False
        )

    def test_every_instance_projects_with_order_and_values(self) -> None:
        configuration = video_profile(
            instance("rpc_a", "event_a", p("a.py")),
            instance("rpc_b", "event_b", p("b.yaml")),
            instance("rpc_c", "event_c", p("c.yml")),
        )

        draft = editable_profile_from(configuration, Path("config.json"))

        assert draft.instances == (
            EditableInstanceConfiguration("rpc_a", "event_a", p("a.py")),
            EditableInstanceConfiguration("rpc_b", "event_b", p("b.yaml")),
            EditableInstanceConfiguration("rpc_c", "event_c", p("c.yml")),
        )

    def test_empty_instances_project_to_empty_draft(self) -> None:
        draft = editable_profile_from(video_profile(), Path("config.json"))

        assert draft.instances == ()

    def test_draft_back_to_profile_keeps_pairs_and_order(self) -> None:
        configuration = video_profile(
            instance("rpc_a", "event_a", p("a.py")),
            instance("rpc_b", "event_b", p("b.yaml")),
        )
        draft = editable_profile_from(configuration, Path("config.json"))

        rebuilt = profile_from_editable(draft)

        assert rebuilt == configuration


class TestInstanceEditing:
    @pytest.mark.parametrize(
        ("field", "value", "expected"),
        [
            ("scenario", p("changed.py"), p("changed.py")),
            ("rpc_endpoint", "tcp://127.0.0.1:54100", "tcp://127.0.0.1:54100"),
            ("event_endpoint", "tcp://127.0.0.1:54101", "tcp://127.0.0.1:54101"),
        ],
    )
    def test_instance_field_edit_changes_only_target(
        self, field: str, value: str, expected: str
    ) -> None:
        model = make_model(profile=multi_profile())

        setter = getattr(model, f"set_instance_{field}")
        draft = setter(1, value)

        assert draft is not None
        assert getattr(draft.instances[1], field) == expected
        assert draft.instances[0] == EditableInstanceConfiguration(
            "rpc_1", "event_1", p("one.py")
        )
        assert draft.instances[2] == EditableInstanceConfiguration(
            "rpc_3", "event_3", p("three.py")
        )


class TestAddInstance:
    def test_appends_empty_instance_to_end(self) -> None:
        model = make_model(profile=multi_profile())

        model.add_instance()

        assert model.draft is not None
        assert len(model.draft.instances) == 4
        assert model.draft.instances[:-1] == (
            EditableInstanceConfiguration("rpc_1", "event_1", p("one.py")),
            EditableInstanceConfiguration("rpc_2", "event_2", p("two.py")),
            EditableInstanceConfiguration("rpc_3", "event_3", p("three.py")),
        )
        assert model.draft.instances[-1] == EditableInstanceConfiguration("", "", "")

    def test_consecutive_adds_append_in_sequence(self) -> None:
        model = make_model(profile=multi_profile())

        model.add_instance()
        model.add_instance()

        assert model.draft is not None
        assert tuple(entry.scenario for entry in model.draft.instances) == (
            p("one.py"),
            p("two.py"),
            p("three.py"),
            "",
            "",
        )


class TestRemoveInstance:
    def test_removes_only_target_and_keeps_order(self) -> None:
        model = make_model(profile=multi_profile())

        model.remove_instance(1)

        assert model.draft is not None
        assert model.draft.instances == (
            EditableInstanceConfiguration("rpc_1", "event_1", p("one.py")),
            EditableInstanceConfiguration("rpc_3", "event_3", p("three.py")),
        )

    @pytest.mark.parametrize(
        ("profile", "index", "expected"),
        [
            (multi_profile(), 0, (p("two.py"), p("three.py"))),
            (multi_profile(), 2, (p("one.py"), p("two.py"))),
            (video_profile(), 0, ()),
        ],
    )
    def test_remove_instance_preserves_expected_instances(
        self, profile, index: int, expected: tuple[str, ...]
    ) -> None:
        model = make_model(profile=profile)

        model.remove_instance(index)

        assert model.draft is not None
        assert tuple(entry.scenario for entry in model.draft.instances) == expected


class TestInstanceValidation:
    def test_zero_instances_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least one instance is required"):
            validate_instances_draft(())

    @pytest.mark.parametrize("scenario", ["", "   ", "\t\n"])
    def test_empty_scenario_is_rejected(self, scenario: str) -> None:
        with pytest.raises(ValueError, match="has an empty scenario"):
            validate_instances_draft(
                (EditableInstanceConfiguration("rpc", "event", scenario),)
            )

    @pytest.mark.parametrize("endpoint", ["", "   "])
    def test_empty_rpc_endpoint_is_rejected(self, endpoint: str) -> None:
        with pytest.raises(ValueError, match="has an empty RPC endpoint"):
            validate_instances_draft(
                (EditableInstanceConfiguration(endpoint, "event", p("s.py")),)
            )

    @pytest.mark.parametrize("endpoint", ["", "   "])
    def test_empty_event_endpoint_is_rejected(self, endpoint: str) -> None:
        with pytest.raises(ValueError, match="has an empty event endpoint"):
            validate_instances_draft(
                (EditableInstanceConfiguration("rpc", endpoint, p("s.py")),)
            )

    def test_duplicate_rpc_endpoint_is_rejected_with_owner(self) -> None:
        with pytest.raises(
            ValueError,
            match="Instance 2 uses the same RPC endpoint as Instance 1.",
        ):
            validate_instances_draft(
                (
                    EditableInstanceConfiguration(
                        "tcp://127.0.0.1:54000", "event_1", p("a.py")
                    ),
                    EditableInstanceConfiguration(
                        "tcp://127.0.0.1:54000", "event_2", "b.py"
                    ),
                )
            )

    def test_duplicate_event_endpoint_is_rejected_with_owner(self) -> None:
        with pytest.raises(
            ValueError,
            match="Instance 2 uses the same event endpoint as Instance 1.",
        ):
            validate_instances_draft(
                (
                    EditableInstanceConfiguration(
                        "rpc_1", "tcp://127.0.0.1:54001", p("a.py")
                    ),
                    EditableInstanceConfiguration(
                        "rpc_2", "tcp://127.0.0.1:54001", "b.py"
                    ),
                )
            )

    def test_valid_multiple_instances_are_accepted(self) -> None:
        validate_instances_draft(
            (
                EditableInstanceConfiguration(
                    "tcp://127.0.0.1:54000", "tcp://127.0.0.1:54001", p("a.py")
                ),
                EditableInstanceConfiguration(
                    "tcp://127.0.0.1:54002", "tcp://127.0.0.1:54003", p("b.yaml")
                ),
            )
        )


class TestRoundTrip:
    def test_configuration_draft_configuration_preserves_instances(self) -> None:
        configuration = video_profile(
            instance("rpc_1", "event_1", p("one.py")),
            instance("rpc_2", "event_2", p("two.yaml")),
        )

        draft = editable_profile_from(configuration, Path("config.json"))
        rebuilt = profile_from_editable(draft)

        assert rebuilt == configuration


class TestScenarioExtensions:
    def test_scenario_formats_save_independently_per_instance(self) -> None:
        model = make_model()
        model.add_instance()
        model.add_instance()
        model.set_instance_scenario(0, p("scenario_a.py"))
        model.set_instance_scenario(1, p("scenario_b.yaml"))
        model.set_instance_scenario(2, p("scenario_c.yml"))
        model.set_instance_rpc_endpoint(1, "rpc_2")
        model.set_instance_event_endpoint(1, "event_2")
        model.set_instance_rpc_endpoint(2, "rpc_3")
        model.set_instance_event_endpoint(2, "event_3")

        configuration = model.profile_document()

        assert configuration is not None
        assert tuple(entry.scenario for entry in configuration.instances) == (
            p("scenario_a.py"),
            p("scenario_b.yaml"),
            p("scenario_c.yml"),
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


class TestCameraModeLabel:
    def test_label_uses_multiply_sign_and_em_dash(self) -> None:
        mode = cast(
            CameraMode,
            SimpleNamespace(width=1920, height=1080, fps=60.0, format="EYUY2"),
        )

        assert camera_mode_label(mode) == "1920 × 1080 @ 60 fps — EYUY2"

    def test_label_falls_back_to_subtype_guid(self) -> None:
        mode = cast(
            CameraMode,
            SimpleNamespace(width=320, height=240, fps=30.0, subtype_guid="YUY2"),
        )

        assert camera_mode_label(mode) == "320 × 240 @ 30 fps — YUY2"


class TestSettingsDecisions:
    @pytest.mark.parametrize(
        ("state", "editable"),
        [
            (SessionState.RUNNING, ("source", "instances", "log_level", "settings")),
            (SessionState.IDLE, ("source", "instances", "log_level", "settings")),
            (SessionState.CONNECTING, ("source", "instances", "log_level", "settings")),
        ],
    )
    def test_edit_permission_for_session_state(
        self, state: SessionState, editable: tuple[str, ...]
    ) -> None:
        permission = edit_permission(state)
        for name in ("source", "instances", "log_level", "settings"):
            assert getattr(permission, name) is (name in editable)

    @pytest.mark.parametrize("state", [SessionState.LOADING, SessionState.STOPPING])
    def test_transition_session_disables_all_configuration_edits(
        self, state: SessionState
    ) -> None:
        permission = edit_permission(state)

        assert not permission.source
        assert not permission.instances
        assert not permission.log_level
        assert not permission.settings

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


def commit(model: SettingsModel) -> None:
    """Validate the draft and commit it, mirroring a successful Apply."""

    model.apply_app_settings(model.validate_app_settings())


class TestReactionTime:
    def test_reaction_time_change_projects_to_app_settings_only(self) -> None:
        model = make_model()
        model.mark_saved()
        assert not model.is_dirty

        model.edit_reaction_time("30")
        commit(model)

        assert not model.is_dirty
        assert model.app_settings_document().reaction_time_ms == 30
        assert model.profile_document() is not None

    @pytest.mark.parametrize("value", ["-1", "abc", "1.5", "", "  "])
    def test_reaction_time_rejects_invalid_value(self, value: str) -> None:
        model = make_model()
        model.edit_reaction_time(value)

        with pytest.raises(ValueError):
            model.validate_app_settings()

    def test_last_profile_is_lifecycle_owned(self, tmp_path: Path) -> None:
        model = make_model()
        target = tmp_path / "smw.json"
        model.set_last_profile(target)

        assert model.app_settings_document().last_profile == str(target)

    def test_running_session_keeps_reaction_time_editable(self) -> None:
        permission = edit_permission(SessionState.RUNNING)

        assert permission.reaction_time


class TestAppSettingsDraft:
    def test_editing_does_not_change_the_applied_settings(self) -> None:
        model = make_model()
        assert not model.app_settings_dirty

        model.edit_theme(Theme.DARK)
        model.edit_log_level("DEBUG")
        model.edit_reaction_time("30")

        assert model.app_settings_dirty
        assert model.applied_app_settings.theme is Theme.LIGHT
        assert model.applied_app_settings.log_level == "OFF"
        assert model.applied_app_settings.reaction_time_ms == 0
        assert model.app_settings_document().ui == UiSettings(Theme.LIGHT)

    def test_apply_commits_and_resets_the_draft(self) -> None:
        model = make_model()
        model.edit_theme(Theme.DARK)
        model.edit_log_level("DEBUG")
        model.edit_reaction_time("30")
        assert model.app_settings_dirty

        commit(model)

        assert not model.app_settings_dirty
        assert model.applied_app_settings.theme is Theme.DARK
        assert model.applied_app_settings.log_level == "DEBUG"
        assert model.applied_app_settings.reaction_time_ms == 30
        assert model.app_settings_draft == AppSettingsDraft(Theme.DARK, "DEBUG", "30")

    def test_unparseable_reaction_time_counts_as_a_change(self) -> None:
        model = make_model()

        model.edit_reaction_time("not a number")

        assert model.app_settings_dirty

    def test_equivalent_reaction_time_is_not_a_change(self) -> None:
        model = make_model()

        model.edit_reaction_time(" 0 ")

        assert not model.app_settings_dirty

    def test_load_seeds_draft_and_applied_equally(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())

        model.load_app_settings(AppSettings(1, "OFF", 0, None, UiSettings(Theme.DARK)))

        assert model.applied_app_settings.theme is Theme.DARK
        assert model.app_settings_draft == AppSettingsDraft(Theme.DARK, "OFF", "0")
        assert not model.app_settings_dirty
        assert not model.is_dirty


class TestThemeSettings:
    def test_default_theme_is_light(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())

        assert model.applied_app_settings.theme is Theme.LIGHT
        assert not model.is_dirty

    def test_loads_theme_from_app_settings(self) -> None:
        model = SettingsModel(FakeCameraEnumerator())

        model.load_app_settings(AppSettings(1, "OFF", 0, None, UiSettings(Theme.DARK)))

        assert model.applied_app_settings.theme is Theme.DARK
        assert not model.is_dirty

    def test_edit_theme_does_not_dirty_the_profile(self) -> None:
        model = make_model()
        model.mark_saved()

        model.edit_theme(Theme.DARK)

        assert model.app_settings_draft.theme is Theme.DARK
        assert model.applied_app_settings.theme is Theme.LIGHT
        assert not model.is_dirty

    def test_theme_projects_to_app_settings_document_after_apply(self) -> None:
        model = make_model()

        model.edit_theme(Theme.DARK)
        commit(model)

        assert model.app_settings_document().ui == UiSettings(Theme.DARK)

    @pytest.mark.parametrize("theme", [Theme.LIGHT, Theme.DARK])
    def test_projection_and_loading_are_symmetric(
        self, tmp_path: Path, theme: Theme
    ) -> None:
        model = make_model()
        model.edit_theme(theme)
        commit(model)
        path = tmp_path / "settings.json"

        save_app_settings(path, model.app_settings_document())
        other = SettingsModel(FakeCameraEnumerator())
        other.load_app_settings(load_app_settings(path))

        assert other.applied_app_settings.theme is theme
