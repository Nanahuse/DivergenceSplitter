#pragma once

#include <imgui.h>

#include "divergencesplitter/configuration/configuration.hpp"

namespace divergencesplitter::ui {

struct SourceTypeRadioLayout {
    ImVec2 camera_min;
    ImVec2 camera_max;
    ImVec2 video_min;
    ImVec2 video_max;
    ImVec2 ndi_min;
    ImVec2 ndi_max;
};

[[nodiscard]] int source_type_index(const SourceConfiguration& source) noexcept;
void switch_profile_source_type(Profile& profile, int type);
// Draws the source-type radios and returns the type after any click in this frame.
[[nodiscard]] int draw_source_type_radio(
    Profile& profile,
    bool ndi_available,
    SourceTypeRadioLayout* layout = nullptr
);

}  // namespace divergencesplitter::ui
