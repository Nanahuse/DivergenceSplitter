#pragma once

#include <imgui.h>

#include <string_view>

namespace divergencesplitter::ui::theme {

enum class Mode {
    light,
    dark,
};

struct Colors {
    ImVec4 active;
    ImVec4 ready;
    ImVec4 connecting;
    ImVec4 failed;
    ImVec4 stopped;
    ImVec4 error;
    ImVec4 warning;
    ImVec4 primary;
    ImVec4 on_primary;
    ImVec4 muted;
    ImVec4 background;
    ImVec4 background_deep;
    ImVec4 surface;
    ImVec4 surface_low;
    ImVec4 surface_high;
    ImVec4 divider;
    ImVec4 outline;
    ImVec4 text;
    ImVec4 text_secondary;
};

[[nodiscard]] Mode mode_from_string(std::string_view value);
[[nodiscard]] std::string_view mode_name(Mode mode);
[[nodiscard]] Colors colors(Mode mode);
void apply(Mode mode, float scale);

}  // namespace divergencesplitter::ui::theme
