#pragma once

#include <imgui.h>

#include <string>
#include <string_view>

#include "image_texture.hpp"

namespace divergencesplitter::ui {

bool input_text(
    const char* label,
    std::string& value,
    ImGuiInputTextFlags flags = 0,
    const char* hint = nullptr
);

void text_muted(std::string_view text);
void text_error_wrapped(std::string_view text);
void text_section_title(std::string_view text);

// Draws the texture centered in the available area while preserving aspect.
void image_fit(const ImageTexture& texture, float max_height, const char* empty_text);

bool primary_button(const char* label, const ImVec2& size = ImVec2(0.0f, 0.0f));

}  // namespace divergencesplitter::ui
