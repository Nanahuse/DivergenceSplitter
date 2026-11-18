#include "ui_helpers.hpp"

#include <algorithm>

#include "theme.hpp"

namespace divergencesplitter::ui {

bool input_text(
    const char* label,
    std::string& value,
    ImGuiInputTextFlags flags,
    const char* hint
) {
    if (value.capacity() < 32) {
        value.reserve(32);
    }
    const auto callback = [](ImGuiInputTextCallbackData* data) -> int {
        if (data->EventFlag == ImGuiInputTextFlags_CallbackResize) {
            auto* text = static_cast<std::string*>(data->UserData);
            text->resize(static_cast<std::size_t>(data->BufTextLen));
            data->Buf = text->data();
        }
        return 0;
    };
    return ImGui::InputTextWithHint(
        label,
        hint != nullptr ? hint : "",
        value.data(),
        value.capacity() + 1,
        flags | ImGuiInputTextFlags_CallbackResize,
        callback,
        &value
    );
}

void text_muted(std::string_view text) {
    ImGui::PushStyleColor(ImGuiCol_Text, ImGui::GetStyle().Colors[ImGuiCol_TextDisabled]);
    ImGui::TextUnformatted(text.data(), text.data() + text.size());
    ImGui::PopStyleColor();
}

void text_error_wrapped(std::string_view text) {
    ImGui::PushStyleColor(ImGuiCol_Text, ImGui::GetStyle().Colors[ImGuiCol_Text]);
    ImGui::PushStyleColor(ImGuiCol_ChildBg, ImGui::GetStyle().Colors[ImGuiCol_FrameBg]);
    ImGui::BeginChild(
        "##error_text",
        ImVec2(0.0f, ImGui::GetTextLineHeightWithSpacing() * 3.0f),
        true
    );
    ImGui::PushStyleColor(ImGuiCol_Text, ImVec4(0.90f, 0.35f, 0.30f, 1.0f));
    ImGui::TextWrapped("%s", std::string{text}.c_str());
    ImGui::PopStyleColor();
    ImGui::EndChild();
    ImGui::PopStyleColor(2);
}

void text_section_title(std::string_view text) {
    ImGui::PushStyleColor(ImGuiCol_Text, ImGui::GetStyle().Colors[ImGuiCol_Text]);
    ImGui::TextUnformatted(text.data(), text.data() + text.size());
    ImGui::PopStyleColor();
}

void image_fit(const ImageTexture& texture, float max_height, const char* empty_text) {
    const ImVec2 available = ImGui::GetContentRegionAvail();
    if (!texture.valid() || available.x <= 0.0f) {
        text_muted(empty_text);
        return;
    }
    const float scale = std::min(
        available.x / static_cast<float>(texture.width()),
        max_height / static_cast<float>(texture.height())
    );
    const ImVec2 size(
        static_cast<float>(texture.width()) * scale,
        static_cast<float>(texture.height()) * scale
    );
    const float indent = std::max(0.0f, (available.x - size.x) * 0.5f);
    ImGui::SetCursorPosX(ImGui::GetCursorPosX() + indent);
    ImGui::Image(reinterpret_cast<ImTextureID>(texture.handle()), size);
}

bool primary_button(const char* label, const ImVec2& size) {
    const auto palette = theme::colors(
        ImGui::GetStyle().Colors[ImGuiCol_WindowBg].x < 0.3f ? theme::Mode::dark
                                                             : theme::Mode::light
    );
    ImGui::PushStyleColor(ImGuiCol_Button, palette.primary);
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, palette.active);
    ImGui::PushStyleColor(ImGuiCol_ButtonActive, palette.primary);
    ImGui::PushStyleColor(ImGuiCol_Text, palette.on_primary);
    const bool pressed = ImGui::Button(label, size);
    ImGui::PopStyleColor(4);
    return pressed;
}

}  // namespace divergencesplitter::ui
