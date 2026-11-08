#include "theme.hpp"

#include <algorithm>
#include <cctype>
#include <string>

namespace divergencesplitter::ui::theme {
namespace {

ImVec4 from_hex(const char* value) {
    const auto channel = [value](int offset) {
        const auto digit = [](char character) {
            if (character >= '0' && character <= '9') return character - '0';
            if (character >= 'a' && character <= 'f') return character - 'a' + 10;
            return character - 'A' + 10;
        };
        return static_cast<float>(digit(value[offset]) * 16 + digit(value[offset + 1])) / 255.0f;
    };
    return ImVec4(channel(1), channel(3), channel(5), 1.0f);
}

ImVec4 with_alpha(ImVec4 color, float alpha) {
    color.w = alpha;
    return color;
}

struct Palette {
    const char* background;
    const char* background_deep;
    const char* surface;
    const char* surface_low;
    const char* surface_high;
    const char* divider;
    const char* outline;
    const char* text;
    const char* text_secondary;
    const char* primary;
    const char* on_primary;
    const char* ready;
    const char* active;
    const char* connecting;
    const char* failed;
    const char* stopped;
    const char* warning;
    const char* error;
    const char* muted;
};

constexpr Palette light_palette{
    "#F7F5F1", "#EFEBE4", "#FFFFFF", "#F4F1EB", "#EAE5DC", "#DDD7CC", "#B8B0A2",
    "#1D1C19", "#676158", "#F08A35", "#FFFFFF", "#4CAF50", "#FFB300", "#FFB300",
    "#E53935", "#9E9E9E", "#FFB300", "#E53935", "#9E9E9E",
};

constexpr Palette dark_palette{
    "#111512", "#0B0E0C", "#1A201B", "#151A16", "#212921", "#354039", "#5E6A60",
    "#E7E1D3", "#B4B2A8", "#F08A35", "#251207", "#78C99A", "#78C99A", "#D4AD54",
    "#E06B64", "#7D8981", "#D4AD54", "#E06B64", "#7D8981",
};

[[nodiscard]] const Palette& palette_for(Mode mode) {
    return mode == Mode::dark ? dark_palette : light_palette;
}

}  // namespace

Mode mode_from_string(std::string_view value) {
    std::string lowered{value};
    std::transform(lowered.begin(), lowered.end(), lowered.begin(), [](unsigned char character) {
        return static_cast<char>(std::tolower(character));
    });
    return lowered == "dark" ? Mode::dark : Mode::light;
}

std::string_view mode_name(Mode mode) {
    return mode == Mode::dark ? "dark" : "light";
}

Colors colors(Mode mode) {
    const auto& palette = palette_for(mode);
    return Colors{
        from_hex(palette.active),
        from_hex(palette.ready),
        from_hex(palette.connecting),
        from_hex(palette.failed),
        from_hex(palette.stopped),
        from_hex(palette.error),
        from_hex(palette.warning),
        from_hex(palette.primary),
        from_hex(palette.on_primary),
        from_hex(palette.muted),
        from_hex(palette.background),
        from_hex(palette.background_deep),
        from_hex(palette.surface),
        from_hex(palette.surface_low),
        from_hex(palette.surface_high),
        from_hex(palette.divider),
        from_hex(palette.outline),
        from_hex(palette.text),
        from_hex(palette.text_secondary),
    };
}

void apply(Mode mode, float scale) {
    ImGuiStyle style;
    if (mode == Mode::dark) {
        ImGui::StyleColorsDark(&style);
    } else {
        ImGui::StyleColorsLight(&style);
    }

    style.WindowPadding = ImVec2(16.0f, 14.0f);
    style.FramePadding = ImVec2(8.0f, 6.0f);
    style.CellPadding = ImVec2(6.0f, 4.0f);
    style.ItemSpacing = ImVec2(8.0f, 6.0f);
    style.ItemInnerSpacing = ImVec2(6.0f, 4.0f);
    style.ScrollbarSize = 14.0f;
    style.GrabMinSize = 10.0f;
    style.WindowRounding = 10.0f;
    style.ChildRounding = 10.0f;
    style.FrameRounding = 7.0f;
    style.PopupRounding = 8.0f;
    style.ScrollbarRounding = 8.0f;
    style.GrabRounding = 6.0f;
    style.TabRounding = 6.0f;
    style.WindowBorderSize = 1.0f;
    style.ChildBorderSize = 1.0f;
    style.FrameBorderSize = 1.0f;
    style.IndentSpacing = 18.0f;

    const auto palette = colors(mode);
    auto& c = style.Colors;
    c[ImGuiCol_Text] = palette.text;
    c[ImGuiCol_TextDisabled] = palette.muted;
    c[ImGuiCol_WindowBg] = palette.background;
    c[ImGuiCol_ChildBg] = ImVec4(0.0f, 0.0f, 0.0f, 0.0f);
    c[ImGuiCol_PopupBg] = palette.surface;
    c[ImGuiCol_Border] = palette.divider;
    c[ImGuiCol_BorderShadow] = ImVec4(0.0f, 0.0f, 0.0f, 0.0f);
    c[ImGuiCol_FrameBg] = palette.surface_low;
    c[ImGuiCol_FrameBgHovered] = palette.surface_high;
    c[ImGuiCol_FrameBgActive] = palette.surface_high;
    c[ImGuiCol_TitleBg] = palette.background_deep;
    c[ImGuiCol_TitleBgActive] = palette.background_deep;
    c[ImGuiCol_TitleBgCollapsed] = palette.background_deep;
    c[ImGuiCol_MenuBarBg] = palette.surface;
    c[ImGuiCol_ScrollbarBg] = ImVec4(0.0f, 0.0f, 0.0f, 0.0f);
    c[ImGuiCol_ScrollbarGrab] = palette.outline;
    c[ImGuiCol_ScrollbarGrabHovered] = palette.text_secondary;
    c[ImGuiCol_ScrollbarGrabActive] = palette.primary;
    c[ImGuiCol_CheckMark] = palette.primary;
    c[ImGuiCol_SliderGrab] = palette.primary;
    c[ImGuiCol_SliderGrabActive] = palette.active;
    c[ImGuiCol_Button] = palette.surface_high;
    c[ImGuiCol_ButtonHovered] = palette.surface;
    c[ImGuiCol_ButtonActive] = palette.divider;
    c[ImGuiCol_Header] = with_alpha(palette.primary, 0.18f);
    c[ImGuiCol_HeaderHovered] = with_alpha(palette.primary, 0.28f);
    c[ImGuiCol_HeaderActive] = with_alpha(palette.primary, 0.38f);
    c[ImGuiCol_Separator] = palette.divider;
    c[ImGuiCol_SeparatorHovered] = palette.primary;
    c[ImGuiCol_SeparatorActive] = palette.primary;
    c[ImGuiCol_ResizeGrip] = with_alpha(palette.outline, 0.6f);
    c[ImGuiCol_ResizeGripHovered] = palette.primary;
    c[ImGuiCol_ResizeGripActive] = palette.active;
    c[ImGuiCol_Tab] = palette.surface_low;
    c[ImGuiCol_TabHovered] = with_alpha(palette.primary, 0.28f);
    c[ImGuiCol_TabActive] = palette.surface;
    c[ImGuiCol_TabUnfocused] = palette.surface_low;
    c[ImGuiCol_TabUnfocusedActive] = palette.surface;
    c[ImGuiCol_PlotLines] = palette.primary;
    c[ImGuiCol_PlotHistogram] = palette.primary;
    c[ImGuiCol_TextSelectedBg] = with_alpha(palette.primary, 0.35f);
    c[ImGuiCol_DragDropTarget] = palette.primary;
    c[ImGuiCol_ModalWindowDimBg] = ImVec4(0.0f, 0.0f, 0.0f, 0.35f);

    style.ScaleAllSizes(scale);
    ImGui::GetStyle() = style;
}

}  // namespace divergencesplitter::ui::theme
