#include "profile_page.hpp"

#include <imgui.h>

#include "profile_source_ui.hpp"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <optional>
#include <string>
#include <variant>

#include "app.hpp"
#include "divergencesplitter/capture/ndi.hpp"
#include "divergencesplitter/scenario/scenario.hpp"
#include "divergencesplitter/text.hpp"
#include "theme.hpp"
#include "ui_helpers.hpp"

namespace divergencesplitter::ui {
namespace {

constexpr FileDialogFilter kVideoFilters[] = {
    {L"Video files", L"*.mp4;*.mkv;*.avi;*.mov"},
    {L"All files", L"*.*"},
};

constexpr FileDialogFilter kScenarioFilters[] = {
    {L"Scenario YAML", L"*.yaml;*.yml"},
    {L"All files", L"*.*"},
};

std::string backend_name(CameraBackend backend) {
    return backend == CameraBackend::direct_show ? "DirectShow" : "Media Foundation";
}

std::string camera_device_label(const CameraDeviceInfo& device) {
    return device.name + " [" + backend_name(device.backend) + "]";
}

std::string camera_mode_label(const CameraModeInfo& mode) {
    char fps[32]{};
    std::snprintf(fps, sizeof(fps), "%.3f", mode.fps);
    return std::to_string(mode.width) + "x" + std::to_string(mode.height) + " @ " + fps +
           " " + mode.format + " (" + (mode.subtype_selectable ? "exact subtype" : "size/FPS") +
           ")";
}

bool source_ready_for_preview(const SourceConfiguration& source) {
    if (std::holds_alternative<CameraSourceConfiguration>(source)) {
        const auto& camera = std::get<CameraSourceConfiguration>(source);
        return !camera.device.name.empty() && camera.mode.width > 0 &&
               camera.mode.height > 0 && camera.mode.fps > 0.0;
    }
    if (std::holds_alternative<VideoSourceConfiguration>(source)) {
        return !std::get<VideoSourceConfiguration>(source).path.empty();
    }
    return ndi_enabled() && !std::get<NdiSourceConfiguration>(source).name.empty();
}

}  // namespace

ProfilePage::ProfilePage(App* app, NdiDiscovery ndi_discovery)
    : app_(app),
      ndi_discovery_(std::move(ndi_discovery)),
      ndi_worker_([this] { return ndi_discovery_(); }) {
    ndi_discovery_available_ = ndi_enabled() || static_cast<bool>(ndi_discovery_);
    if (!ndi_discovery_) {
        ndi_discovery_ = [] { return discover_ndi_sources(); };
    }
    load_draft(app_->document().draft);
}

ProfilePage::~ProfilePage() {
    stop_preview();
    ndi_worker_.stop();
}

Profile ProfilePage::draft_profile() const {
    return app_->document().draft;
}

void ProfilePage::load_draft(const Profile& profile) {
    stop_preview();
    app_->document().draft = profile;
    camera_devices_loaded_ = false;
    camera_devices_.clear();
    camera_modes_.clear();
    camera_note_.clear();
    next_preview_ = 0.0;
}

void ProfilePage::reload_draft() {
    load_draft(app_->document().draft);
}

void ProfilePage::suspend_preview() {
    preview_suspended_ = true;
    stop_preview();
    preview_status_ = "Preview paused while the Session starts.";
}

void ProfilePage::resume_preview() {
    preview_suspended_ = false;
    next_preview_ = 0.0;
}

void ProfilePage::update(bool visible, double now) {
    if (!visible) {
        if (visible_) {
            stop_preview();
        }
        visible_ = false;
        return;
    }
    if (!visible_) {
        visible_ = true;
        next_preview_ = 0.0;
    }
    poll_ndi_discovery();
    if (std::holds_alternative<CameraSourceConfiguration>(app_->document().draft.source) &&
        !camera_devices_loaded_) {
        refresh_camera_devices();
    }
    if (now >= next_preview_) {
        next_preview_ = now + 0.1;
        refresh_preview();
    }
    if (std::holds_alternative<NdiSourceConfiguration>(app_->document().draft.source) &&
        ndi_discovery_available_ && !ndi_worker_.busy() && now - ndi_last_search_ >= 5.0) {
        refresh_ndi_sources();
    }
}

void ProfilePage::stop_preview() {
    preview_worker_.stop();
    preview_texture_.clear();
    preview_status_ = "Preview stopped.";
}

void ProfilePage::refresh_preview() {
    const auto& session = app_->controller().session();
    if (!visible_ || !preview_enabled_ || preview_suspended_ || session.running()) {
        stop_preview();
        if (session.running() || preview_suspended_) {
            preview_status_ =
                "Preview stopped while a Session is active. Stop the Session to preview "
                "draft settings.";
        }
        return;
    }
    if (!source_ready_for_preview(app_->document().draft.source)) {
        stop_preview();
        preview_status_ = "Select an input source to preview.";
        return;
    }
    preview_worker_.configure(app_->document().draft.source);
    const auto snapshot = preview_worker_.snapshot();
    if (!snapshot.error.empty()) {
        preview_texture_.clear();
        preview_status_ = "Preview: " + snapshot.error +
                          ". Edit the source or toggle Preview input to retry.";
        return;
    }
    if (snapshot.image.empty()) {
        preview_texture_.clear();
        preview_status_ = "Opening input / waiting for a frame...";
        return;
    }
    if (!preview_texture_.update(app_->device(), app_->context(), snapshot.image)) {
        preview_status_ = "Could not upload the preview image.";
        return;
    }
    char text[256]{};
    std::snprintf(
        text,
        sizeof(text),
        "Opened input: %d x %d, %.2f fps reported | %.1f fps received | Output: %d x %d",
        snapshot.input.width,
        snapshot.input.height,
        snapshot.input.fps,
        snapshot.measured_fps,
        snapshot.image.cols,
        snapshot.image.rows
    );
    preview_status_ = text;
}

void ProfilePage::ensure_camera_devices() {
    if (!camera_devices_loaded_) {
        refresh_camera_devices();
    }
}

void ProfilePage::refresh_camera_devices() {
    try {
        camera_devices_ = list_camera_devices();
        camera_devices_loaded_ = true;
    } catch (const std::exception& error) {
        camera_devices_.clear();
        camera_modes_.clear();
        camera_devices_loaded_ = true;
        camera_note_ = std::string{"Could not enumerate cameras: "} + error.what();
        return;
    }
    if (camera_devices_.empty()) {
        camera_modes_.clear();
        camera_note_ = "No camera devices were found.";
        return;
    }
    if (!std::holds_alternative<CameraSourceConfiguration>(app_->document().draft.source)) {
        return;
    }
    const auto& camera = std::get<CameraSourceConfiguration>(app_->document().draft.source);
    const auto resolved = resolve_camera_device(camera.device, camera_devices_);
    if (!resolved.has_value()) {
        camera_modes_.clear();
        camera_note_ = "The configured camera is not connected.";
        return;
    }
    populate_camera_modes(resolved->modes, camera.mode);
}

void ProfilePage::populate_camera_modes(
    const std::vector<CameraModeInfo>& modes,
    const std::optional<CameraModeConfiguration>& configured
) {
    camera_modes_ = modes;
    camera_note_.clear();
    if (modes.empty()) {
        camera_note_ = "The selected camera reports no capture modes.";
        return;
    }
    if (configured.has_value()) {
        const auto resolved = try_resolve_camera_mode(*configured, modes);
        if (!resolved.has_value()) {
            camera_note_ = "The configured capture mode is unavailable.";
            return;
        }
        camera_note_ = resolved->subtype_selectable
            ? "The capture backend can select and verify this exact subtype."
            : "This mode verifies width/height/FPS only; OpenCV does not expose exact "
              "subtype selection for this backend.";
    }
}

void ProfilePage::select_camera_device(int index) {
    if (index < 0 || index >= static_cast<int>(camera_devices_.size())) {
        return;
    }
    auto& camera = std::get<CameraSourceConfiguration>(app_->document().draft.source);
    const auto& device = camera_devices_[static_cast<std::size_t>(index)];
    camera.device.name = device.name;
    camera.device.index = device.index;
    camera.device.backend = device.backend;
    populate_camera_modes(device.modes, camera.mode);
    if (!try_resolve_camera_mode(camera.mode, device.modes).has_value() &&
        !device.modes.empty()) {
        select_camera_mode(0);
    }
    next_preview_ = 0.0;
}

void ProfilePage::select_camera_mode(int index) {
    if (index < 0 || index >= static_cast<int>(camera_modes_.size())) {
        return;
    }
    auto& camera = std::get<CameraSourceConfiguration>(app_->document().draft.source);
    const auto& mode = camera_modes_[static_cast<std::size_t>(index)];
    camera.mode.width = mode.width;
    camera.mode.height = mode.height;
    camera.mode.fps = mode.fps;
    camera.mode.subtype_guid = mode.subtype_guid;
    camera_note_ = mode.subtype_selectable
        ? "The capture backend can select and verify this exact subtype."
        : "This mode verifies width/height/FPS only; OpenCV does not expose exact subtype "
          "selection for this backend.";
    next_preview_ = 0.0;
}

void ProfilePage::draw() {
    draw_toolbar();
    const float scale = app_->dpi_scale();
    const float actions_height = 76.0f * scale;
    const float tab_height =
        std::max(120.0f * scale, ImGui::GetContentRegionAvail().y - actions_height);
    ImGui::BeginChild("##profile_tab_area", ImVec2(0.0f, tab_height), false);
    if (ImGui::BeginTabBar("##profile_tabs")) {
        if (ImGui::BeginTabItem("Input")) {
            draw_input_tab();
            ImGui::EndTabItem();
        }
        if (ImGui::BeginTabItem("Scenarios & Connections")) {
            draw_scenarios_tab();
            ImGui::EndTabItem();
        }
        ImGui::EndTabBar();
    }
    ImGui::EndChild();
    draw_actions();
}

void ProfilePage::draw_toolbar() {
    const auto palette = theme::colors(app_->theme_mode());
    const float scale = app_->dpi_scale();
    ImGui::Indent(12.0f * scale);
    ImGui::Dummy(ImVec2(0.0f, 6.0f * scale));
    ImGui::PushStyleColor(ImGuiCol_Text, palette.text);
    ImGui::TextUnformatted("Profile");
    ImGui::PopStyleColor();
    if (app_->document().dirty()) {
        ImGui::SameLine();
        ImGui::PushStyleColor(ImGuiCol_Text, palette.warning);
        ImGui::TextUnformatted("Unsaved changes");
        ImGui::PopStyleColor();
    }

    std::string path_text = app_->document().path.has_value()
        ? path_to_utf8(*app_->document().path)
        : "No profile selected";
    const float buttons_width = 300.0f * scale;
    ImGui::SetNextItemWidth(
        std::max(180.0f * scale, ImGui::GetContentRegionAvail().x - buttons_width)
    );
    input_text("##profile_path", path_text, ImGuiInputTextFlags_ReadOnly);
    ImGui::SameLine();
    if (ImGui::Button("New")) {
        app_->new_profile();
    }
    ImGui::SameLine();
    if (ImGui::Button("Open")) {
        app_->open_profile();
    }
    ImGui::SameLine();
    if (ImGui::Button("Save")) {
        app_->save_profile();
    }
    ImGui::SameLine();
    if (ImGui::Button("Save As")) {
        app_->save_profile_as();
    }
    ImGui::Dummy(ImVec2(0.0f, 4.0f * scale));
    ImGui::Unindent(12.0f * scale);
}

void ProfilePage::draw_input_tab() {
    ImGui::BeginChild("##input_scroll", ImVec2(0.0f, 0.0f), false);
    const auto palette = theme::colors(app_->theme_mode());
    const float scale = app_->dpi_scale();
    const float gap = 12.0f * scale;
    ImGui::Indent(12.0f * scale);
    const float available = ImGui::GetContentRegionAvail().x;
    const float source_width = std::max(320.0f * scale, (available - gap) * 0.55f);
    const float panel_height = 430.0f * scale;

    ImGui::PushStyleColor(ImGuiCol_ChildBg, palette.surface);
    ImGui::BeginChild("##source_panel", ImVec2(source_width, panel_height), true);
    ImGui::PopStyleColor();
    ImGui::Indent(8.0f * scale);
    draw_source_controls();
    ImGui::Unindent(8.0f * scale);
    ImGui::EndChild();

    ImGui::SameLine(0.0f, gap);
    ImGui::PushStyleColor(ImGuiCol_ChildBg, palette.surface);
    ImGui::BeginChild("##preview_panel", ImVec2(0.0f, panel_height), true);
    ImGui::PopStyleColor();
    ImGui::Indent(8.0f * scale);
    draw_preview();
    ImGui::Unindent(8.0f * scale);
    ImGui::EndChild();

    draw_transform_controls();
    ImGui::Unindent(12.0f * scale);
    ImGui::EndChild();
}

void ProfilePage::draw_source_controls() {
    ImGui::SeparatorText("Input source");
    const int type = draw_source_type_radio(
        app_->document().draft,
        ndi_enabled()
    );
    ImGui::Dummy(ImVec2(0.0f, 4.0f * app_->dpi_scale()));
    switch (type) {
        case 0:
            draw_camera_source();
            break;
        case 1:
            draw_video_source();
            break;
        default:
            draw_ndi_source();
            break;
    }
}

void ProfilePage::draw_camera_source() {
    auto& camera = std::get<CameraSourceConfiguration>(app_->document().draft.source);
    ensure_camera_devices();

    int selected_device = -1;
    const auto resolved = resolve_camera_device(camera.device, camera_devices_);
    if (resolved.has_value()) {
        for (std::size_t index = 0; index < camera_devices_.size(); ++index) {
            if (camera_devices_[index].backend == resolved->backend &&
                camera_devices_[index].index == resolved->index) {
                selected_device = static_cast<int>(index);
                break;
            }
        }
    }
    const std::string device_label = selected_device >= 0
        ? camera_device_label(camera_devices_[static_cast<std::size_t>(selected_device)])
        : "Select a camera";
    const float detect_width =
        ImGui::CalcTextSize("Detect cameras").x + ImGui::GetStyle().FramePadding.x * 2.0f;
    ImGui::SetNextItemWidth(
        std::max(
            160.0f * app_->dpi_scale(),
            ImGui::GetContentRegionAvail().x - detect_width -
                ImGui::GetStyle().ItemSpacing.x
        )
    );
    if (ImGui::BeginCombo("Device", device_label.c_str())) {
        for (int index = 0; index < static_cast<int>(camera_devices_.size()); ++index) {
            const bool selected = index == selected_device;
            const std::string label = camera_device_label(
                camera_devices_[static_cast<std::size_t>(index)]
            );
            if (ImGui::Selectable(label.c_str(), selected)) {
                select_camera_device(index);
            }
            if (selected) {
                ImGui::SetItemDefaultFocus();
            }
        }
        ImGui::EndCombo();
    }
    if (ImGui::Button("Detect cameras")) {
        refresh_camera_devices();
    }

    input_text("Device name", camera.device.name);

    int selected_mode = -1;
    const auto resolved_mode = try_resolve_camera_mode(camera.mode, camera_modes_);
    if (resolved_mode.has_value()) {
        for (std::size_t index = 0; index < camera_modes_.size(); ++index) {
            if (camera_modes_[index] == *resolved_mode) {
                selected_mode = static_cast<int>(index);
                break;
            }
        }
    }
    const std::string mode_label = selected_mode >= 0
        ? camera_mode_label(camera_modes_[static_cast<std::size_t>(selected_mode)])
        : "Select a mode";
    if (ImGui::BeginCombo("Mode", mode_label.c_str())) {
        for (int index = 0; index < static_cast<int>(camera_modes_.size()); ++index) {
            const bool selected = index == selected_mode;
            const std::string label = camera_mode_label(
                camera_modes_[static_cast<std::size_t>(index)]
            );
            if (ImGui::Selectable(label.c_str(), selected)) {
                select_camera_mode(index);
            }
            if (selected) {
                ImGui::SetItemDefaultFocus();
            }
        }
        ImGui::EndCombo();
    }

    const int backend_index = camera.device.backend == CameraBackend::direct_show ? 1 : 0;
    const char* backends[] = {"Media Foundation", "DirectShow"};
    if (ImGui::BeginCombo("Backend", backends[backend_index])) {
        for (int index = 0; index < 2; ++index) {
            const bool selected = index == backend_index;
            if (ImGui::Selectable(backends[index], selected)) {
                camera.device.backend = index == 1 ? CameraBackend::direct_show
                                                   : CameraBackend::media_foundation;
                next_preview_ = 0.0;
            }
            if (selected) {
                ImGui::SetItemDefaultFocus();
            }
        }
        ImGui::EndCombo();
    }

    ImGui::SetNextItemWidth(120.0f * app_->dpi_scale());
    ImGui::InputInt("Device index", &camera.device.index);
    camera.device.index = std::max(0, camera.device.index);

    ImGui::SetNextItemWidth(120.0f * app_->dpi_scale());
    ImGui::InputInt("Width", &camera.mode.width);
    camera.mode.width = std::max(1, camera.mode.width);
    ImGui::SameLine();
    ImGui::SetNextItemWidth(120.0f * app_->dpi_scale());
    ImGui::InputInt("Height", &camera.mode.height);
    camera.mode.height = std::max(1, camera.mode.height);

    ImGui::SetNextItemWidth(120.0f * app_->dpi_scale());
    ImGui::InputDouble("FPS", &camera.mode.fps, 1.0, 10.0, "%.3f");
    camera.mode.fps = std::max(0.1, camera.mode.fps);

    input_text("Subtype GUID", camera.mode.subtype_guid);
    ImGui::Checkbox("Request 60 fps", &camera.request_60_fps);

    if (!camera_note_.empty()) {
        ImGui::PushTextWrapPos(ImGui::GetContentRegionAvail().x);
        text_muted(camera_note_);
        ImGui::PopTextWrapPos();
    }
}

void ProfilePage::draw_video_source() {
    auto& video = std::get<VideoSourceConfiguration>(app_->document().draft.source);
    ImGui::SetNextItemWidth(
        std::max(180.0f * app_->dpi_scale(), ImGui::GetContentRegionAvail().x - 90.0f * app_->dpi_scale())
    );
    if (input_text("##video_path", video.path, 0, "Absolute path to a video file")) {
        next_preview_ = 0.0;
    }
    ImGui::SameLine();
    if (ImGui::Button("Browse...")) {
        browse_video();
    }
}

void ProfilePage::draw_ndi_source() {
    auto& ndi = std::get<NdiSourceConfiguration>(app_->document().draft.source);
    ImGui::SetNextItemWidth(
        std::max(220.0f * app_->dpi_scale(), ImGui::GetContentRegionAvail().x - 110.0f * app_->dpi_scale())
    );
    if (input_text(
            "##ndi_name",
            ndi.name,
            0,
            "Advertised source name (kept when offline)"
        )) {
        next_preview_ = 0.0;
    }
    ImGui::SameLine();
    ImGui::BeginDisabled(!ndi_discovery_available_ || ndi_worker_.busy());
    if (ImGui::Button("Search again")) {
        refresh_ndi_sources();
    }
    ImGui::EndDisabled();

    if (!ndi_enabled()) {
        ImGui::PushTextWrapPos(ImGui::GetContentRegionAvail().x);
        text_muted(ndi_runtime_status().message);
        text_muted(
            "Install NDI Runtime from https://ndi.video/ and restart DivergenceSplitter."
        );
        ImGui::PopTextWrapPos();
    } else if (!ndi_notice_.empty()) {
        ImGui::PushTextWrapPos(ImGui::GetContentRegionAvail().x);
        text_muted(ndi_notice_);
        ImGui::PopTextWrapPos();
    } else {
        text_muted("Select a source or enter its saved name.");
    }

    if (!ndi_sources_.empty()) {
        ImGui::BeginChild("##ndi_sources", ImVec2(0.0f, 120.0f * app_->dpi_scale()), true);
        for (const auto& name : ndi_sources_) {
            const bool selected = ndi.name == name;
            if (ImGui::Selectable(name.c_str(), selected)) {
                ndi.name = name;
                next_preview_ = 0.0;
            }
        }
        ImGui::EndChild();
    }

    ImGui::PushTextWrapPos(ImGui::GetContentRegionAvail().x);
    text_muted(
        "NDI® is a registered trademark of Vizrt NDI AB. The NDI runtime is not "
        "bundled and is separately licensed. See licenses/NDI-TERMS.txt in the "
        "distribution for its use terms."
    );
    ImGui::PopTextWrapPos();
}

void ProfilePage::draw_transform_controls() {
    ImGui::SeparatorText("Frame Processing");
    auto& transform = std::visit(
        [](auto& source) -> TransformConfiguration& { return source.transform; },
        app_->document().draft.source
    );

    bool crop = transform.crop.has_value();
    if (ImGui::Checkbox("Crop margins", &crop)) {
        if (crop) {
            transform.crop = CropConfiguration{};
        } else {
            transform.crop.reset();
        }
        next_preview_ = 0.0;
    }
    if (transform.crop.has_value()) {
        ImGui::SameLine();
        const float width = 80.0f * app_->dpi_scale();
        ImGui::TextUnformatted("L");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(width);
        ImGui::InputInt("##crop_left", &transform.crop->left, 0, 0);
        ImGui::SameLine();
        ImGui::TextUnformatted("R");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(width);
        ImGui::InputInt("##crop_right", &transform.crop->right, 0, 0);
        ImGui::SameLine();
        ImGui::TextUnformatted("T");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(width);
        ImGui::InputInt("##crop_top", &transform.crop->top, 0, 0);
        ImGui::SameLine();
        ImGui::TextUnformatted("B");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(width);
        ImGui::InputInt("##crop_bottom", &transform.crop->bottom, 0, 0);
        transform.crop->left = std::max(0, transform.crop->left);
        transform.crop->right = std::max(0, transform.crop->right);
        transform.crop->top = std::max(0, transform.crop->top);
        transform.crop->bottom = std::max(0, transform.crop->bottom);
        next_preview_ = 0.0;
    }

    bool resize = transform.resize.has_value();
    if (ImGui::Checkbox("Resize", &resize)) {
        if (resize) {
            transform.resize = ResizeConfiguration{1280, 720};
        } else {
            transform.resize.reset();
        }
        next_preview_ = 0.0;
    }
    if (transform.resize.has_value()) {
        ImGui::SameLine();
        ImGui::TextUnformatted("W");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(90.0f * app_->dpi_scale());
        ImGui::InputInt("##resize_width", &transform.resize->width, 0, 0);
        ImGui::SameLine();
        ImGui::TextUnformatted("H");
        ImGui::SameLine();
        ImGui::SetNextItemWidth(90.0f * app_->dpi_scale());
        ImGui::InputInt("##resize_height", &transform.resize->height, 0, 0);
        transform.resize->width = std::max(1, transform.resize->width);
        transform.resize->height = std::max(1, transform.resize->height);

        ImGui::SameLine();
        const char* interpolations[] = {"area", "nearest", "linear", "cubic", "lanczos4"};
        const int current = std::clamp(
            static_cast<int>(transform.resize->interpolation),
            0,
            4
        );
        if (ImGui::BeginCombo("Interpolation", interpolations[current])) {
            for (int index = 0; index < 5; ++index) {
                const bool selected = index == current;
                if (ImGui::Selectable(interpolations[index], selected)) {
                    transform.resize->interpolation =
                        static_cast<ResizeInterpolation>(index);
                    next_preview_ = 0.0;
                }
                if (selected) {
                    ImGui::SetItemDefaultFocus();
                }
            }
            ImGui::EndCombo();
        }
        if (ImGui::Checkbox(
                "Resize reference images",
                &transform.resize->resize_references
            )) {
            next_preview_ = 0.0;
        }
    }
}

void ProfilePage::draw_preview() {
    ImGui::SeparatorText("Input Preview");
    if (ImGui::Checkbox("Preview input", &preview_enabled_)) {
        next_preview_ = 0.0;
    }
    image_fit(preview_texture_, 270.0f * app_->dpi_scale(), "No input");
    if (!preview_status_.empty()) {
        ImGui::PushTextWrapPos(ImGui::GetContentRegionAvail().x);
        text_muted(preview_status_);
        ImGui::PopTextWrapPos();
    }
    if (app_->controller().session().running()) {
        if (ImGui::Button("Stop Session and preview draft")) {
            app_->controller().stop();
            next_preview_ = 0.0;
            app_->notify("Session stopped.");
        }
    }
}

void ProfilePage::draw_scenarios_tab() {
    ImGui::BeginChild("##scenarios_scroll", ImVec2(0.0f, 0.0f), false);
    ImGui::Indent(12.0f * app_->dpi_scale());
    ImGui::SeparatorText("LiveSplit Instances");

    auto& instances = app_->document().draft.instances;
    int remove_index = -1;
    if (ImGui::BeginTable(
            "##instances",
            4,
            ImGuiTableFlags_Borders | ImGuiTableFlags_RowBg |
                ImGuiTableFlags_SizingStretchProp | ImGuiTableFlags_Resizable
        )) {
        ImGui::TableSetupColumn("Bridge port", ImGuiTableColumnFlags_WidthFixed, 110.0f);
        ImGui::TableSetupColumn("Scenario YAML", ImGuiTableColumnFlags_WidthStretch);
        ImGui::TableSetupColumn("Browse", ImGuiTableColumnFlags_WidthFixed, 80.0f);
        ImGui::TableSetupColumn("Remove", ImGuiTableColumnFlags_WidthFixed, 80.0f);
        ImGui::TableHeadersRow();
        for (std::size_t index = 0; index < instances.size(); ++index) {
            ImGui::TableNextRow();
            ImGui::TableNextColumn();
            ImGui::SetNextItemWidth(-1.0f);
            ImGui::InputInt(
                ("##port_" + std::to_string(index)).c_str(),
                &instances[index].connection.port
            );
            ImGui::TableNextColumn();
            ImGui::SetNextItemWidth(-1.0f);
            input_text(
                ("##scenario_" + std::to_string(index)).c_str(),
                instances[index].scenario,
                0,
                "Absolute path to scenario YAML"
            );
            ImGui::TableNextColumn();
            if (ImGui::Button(("Browse##" + std::to_string(index)).c_str())) {
                browse_scenario(index);
            }
            ImGui::TableNextColumn();
            if (ImGui::Button(("Remove##" + std::to_string(index)).c_str())) {
                remove_index = static_cast<int>(index);
            }
        }
        ImGui::EndTable();
    }
    if (remove_index >= 0 && remove_index < static_cast<int>(instances.size())) {
        instances.erase(instances.begin() + remove_index);
    }
    if (ImGui::Button("Add instance")) {
        InstanceConfiguration instance;
        instance.connection.port = 54000 + static_cast<int>(instances.size());
        instances.push_back(std::move(instance));
    }
    ImGui::Unindent(12.0f * app_->dpi_scale());
    ImGui::EndChild();
}

void ProfilePage::draw_actions() {
    ImGui::Indent(12.0f * app_->dpi_scale());
    if (!status_.empty()) {
        ImGui::PushTextWrapPos(ImGui::GetContentRegionAvail().x);
        text_muted(status_);
        ImGui::PopTextWrapPos();
    }
    ImGui::Dummy(ImVec2(0.0f, 2.0f * app_->dpi_scale()));
    if (ImGui::Button("Revert draft")) {
        auto& document = app_->document();
        document.revert_draft(app_->controller().profile());
        load_draft(document.draft);
        status_ = "Draft reverted.";
    }
    ImGui::SameLine();
    ImGui::Dummy(ImVec2(
        std::max(0.0f, ImGui::GetContentRegionAvail().x - 100.0f * app_->dpi_scale()),
        0.0f
    ));
    ImGui::SameLine();
    if (primary_button("Apply")) {
        apply();
    }
    ImGui::Dummy(ImVec2(0.0f, 6.0f * app_->dpi_scale()));
    ImGui::Unindent(12.0f * app_->dpi_scale());
}

void ProfilePage::apply() {
    const Profile profile = draft_profile();
    const auto fail = [this](const std::string& message) {
        status_ = message;
        app_->notify(message, true);
    };

    if (std::holds_alternative<CameraSourceConfiguration>(profile.source)) {
        const auto& camera = std::get<CameraSourceConfiguration>(profile.source);
        if (camera.device.name.empty()) {
            fail("A camera device name is required. Use Detect cameras to select one.");
            return;
        }
        if (camera.mode.width <= 0 || camera.mode.height <= 0 || camera.mode.fps <= 0.0) {
            fail("A camera capture mode is required. Use Detect cameras to select one.");
            return;
        }
        if (camera.mode.subtype_guid.empty()) {
            fail("A camera subtype GUID is required. Use Detect cameras to select a mode.");
            return;
        }
    }
    if (std::holds_alternative<NdiSourceConfiguration>(profile.source)) {
        if (!ndi_enabled()) {
            fail("NDI Runtime is unavailable: " + ndi_runtime_status().message);
            return;
        }
        if (std::get<NdiSourceConfiguration>(profile.source).name.empty()) {
            fail("An NDI source name is required.");
            return;
        }
    }
    if (std::holds_alternative<VideoSourceConfiguration>(profile.source)) {
        const auto& video = std::get<VideoSourceConfiguration>(profile.source);
        if (video.path.empty()) {
            fail("A video file path is required.");
            return;
        }
        if (!path_from_utf8(video.path).is_absolute()) {
            fail("The video file path must be absolute.");
            return;
        }
    }

    if (profile.instances.empty()) {
        fail("Add at least one LiveSplit instance.");
        return;
    }
    for (const auto& instance : profile.instances) {
        if (instance.connection.port < 1 || instance.connection.port > 65535) {
            fail("Bridge ports must be between 1 and 65535.");
            return;
        }
        const std::filesystem::path scenario = path_from_utf8(instance.scenario);
        if (instance.scenario.empty() || !scenario.is_absolute()) {
            fail("Every scenario path must be absolute.");
            return;
        }
        if (scenario.extension() == ".py") {
            fail("Python scenario modules are not supported: " + instance.scenario);
            return;
        }
        try {
            (void)load_profile_scenario(scenario, profile.source);
        } catch (const std::exception& error) {
            fail(std::string{"Scenario validation failed: "} + error.what());
            return;
        }
    }

    stop_preview();
    preview_suspended_ = false;
    std::string error;
    if (!app_->controller().apply_profile(profile, &error)) {
        fail("Could not apply profile: " + error);
        next_preview_ = 0.0;
        return;
    }
    status_ = "Profile applied.";
    app_->notify("Profile applied.");
    next_preview_ = 0.0;
}

void ProfilePage::browse_video() {
    auto& video = std::get<VideoSourceConfiguration>(app_->document().draft.source);
    std::optional<std::filesystem::path> initial;
    if (!video.path.empty()) {
        initial = path_from_utf8(video.path);
    }
    const auto path = app_->pick_open_file(L"Select video", kVideoFilters, initial);
    if (path.has_value()) {
        video.path = path_to_utf8(*path);
        next_preview_ = 0.0;
    }
}

void ProfilePage::browse_scenario(std::size_t index) {
    auto& instances = app_->document().draft.instances;
    if (index >= instances.size()) {
        return;
    }
    std::optional<std::filesystem::path> initial;
    if (!instances[index].scenario.empty()) {
        initial = path_from_utf8(instances[index].scenario);
    }
    const auto path = app_->pick_open_file(L"Select scenario", kScenarioFilters, initial);
    if (path.has_value()) {
        instances[index].scenario = path_to_utf8(*path);
    }
}

void ProfilePage::refresh_ndi_sources() {
    if (!ndi_discovery_available_ || ndi_worker_.busy()) {
        return;
    }
    ndi_last_search_ = ImGui::GetTime();
    ndi_notice_ = "Searching for NDI sources...";
    ndi_worker_.start();
}

void ProfilePage::poll_ndi_discovery() {
    auto result = ndi_worker_.take_result();
    if (!result.has_value()) {
        return;
    }
    ndi_sources_ = std::move(result->sources);
    if (!result->error.empty()) {
        ndi_notice_ = "NDI discovery failed: " + result->error;
        return;
    }
    const auto& draft = app_->document().draft;
    const std::string selected = std::holds_alternative<NdiSourceConfiguration>(draft.source)
        ? std::get<NdiSourceConfiguration>(draft.source).name
        : std::string{};
    if (ndi_sources_.empty()) {
        ndi_notice_ = "No NDI sources found. The saved name is retained.";
    } else if (!selected.empty() &&
               std::find(ndi_sources_.begin(), ndi_sources_.end(), selected) ==
                   ndi_sources_.end()) {
        ndi_notice_ = "Saved source is currently offline: " + selected;
    } else {
        ndi_notice_ = std::to_string(ndi_sources_.size()) + " NDI source(s) found.";
    }
}

}  // namespace divergencesplitter::ui
