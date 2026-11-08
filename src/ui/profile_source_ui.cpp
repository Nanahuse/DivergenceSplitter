#include "profile_source_ui.hpp"

#include <variant>

namespace divergencesplitter::ui {

int source_type_index(const SourceConfiguration& source) noexcept {
    if (std::holds_alternative<CameraSourceConfiguration>(source)) return 0;
    if (std::holds_alternative<VideoSourceConfiguration>(source)) return 1;
    return 2;
}

void switch_profile_source_type(Profile& profile, int type) {
    const TransformConfiguration transform = std::visit(
        [](const auto& value) { return value.transform; },
        profile.source
    );
    if (type == 0 && !std::holds_alternative<CameraSourceConfiguration>(profile.source)) {
        CameraSourceConfiguration camera;
        camera.mode.width = 1920;
        camera.mode.height = 1080;
        camera.mode.fps = 60.0;
        camera.transform = transform;
        profile.source = std::move(camera);
    } else if (type == 1 &&
               !std::holds_alternative<VideoSourceConfiguration>(profile.source)) {
        profile.source = VideoSourceConfiguration{"", transform};
    } else if (type == 2 &&
               !std::holds_alternative<NdiSourceConfiguration>(profile.source)) {
        profile.source = NdiSourceConfiguration{"", transform};
    }
}

int draw_source_type_radio(
    Profile& profile,
    bool ndi_available,
    SourceTypeRadioLayout* layout
) {
    const int initial_type = source_type_index(profile.source);
    if (ImGui::RadioButton("Camera", initial_type == 0)) {
        switch_profile_source_type(profile, 0);
    }
    if (layout != nullptr) {
        layout->camera_min = ImGui::GetItemRectMin();
        layout->camera_max = ImGui::GetItemRectMax();
    }
    ImGui::SameLine();
    if (ImGui::RadioButton("Video file", initial_type == 1)) {
        switch_profile_source_type(profile, 1);
    }
    if (layout != nullptr) {
        layout->video_min = ImGui::GetItemRectMin();
        layout->video_max = ImGui::GetItemRectMax();
    }
    ImGui::SameLine();
    ImGui::BeginDisabled(!ndi_available && initial_type != 2);
    if (ImGui::RadioButton("NDI", initial_type == 2)) {
        switch_profile_source_type(profile, 2);
    }
    ImGui::EndDisabled();
    if (layout != nullptr) {
        layout->ndi_min = ImGui::GetItemRectMin();
        layout->ndi_max = ImGui::GetItemRectMax();
    }
    // The clicked radio may have changed the variant during this frame.
    return source_type_index(profile.source);
}

}  // namespace divergencesplitter::ui
