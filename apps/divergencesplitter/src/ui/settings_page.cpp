#include "settings_page.hpp"

#include <imgui.h>

#include <algorithm>
#include <array>

#include "app.hpp"
#include "theme.hpp"
#include "ui_helpers.hpp"

namespace divergencesplitter::ui {
namespace {

constexpr std::array<const char*, 5> kLogLevels{
    "OFF", "DEBUG", "INFO", "WARNING", "ERROR",
};

int log_level_index(const std::string& value) {
    const auto found = std::find(kLogLevels.begin(), kLogLevels.end(), value);
    return found == kLogLevels.end() ? 2 : static_cast<int>(found - kLogLevels.begin());
}

}  // namespace

SettingsPage::SettingsPage(App* app) : app_(app) {
    reload();
}

void SettingsPage::reload() {
    const auto& settings = app_->controller().settings();
    theme_index_ = settings.theme == "dark" ? 1 : 0;
    reaction_time_ms_ = settings.reaction_time_ms;
    log_level_index_ = log_level_index(settings.log_level);
    status_ = "Settings loaded. Reaction time applies on the next Apply.";
}

void SettingsPage::draw() {
    ImGui::Dummy(ImVec2(0.0f, 8.0f));
    ImGui::Indent(16.0f);
    ImGui::PushStyleColor(ImGuiCol_Text, theme::colors(app_->theme_mode()).text);
    ImGui::TextUnformatted("Application Settings");
    ImGui::PopStyleColor();
    text_muted("Edit the values, then select Apply to save and apply them.");
    ImGui::Spacing();

    const float scale = app_->dpi_scale();
    const float actions_height = 76.0f * scale;
    const float scroll_height =
        std::max(120.0f * scale, ImGui::GetContentRegionAvail().y - actions_height);
    ImGui::BeginChild("##settings_scroll", ImVec2(0.0f, scroll_height), false);
    ImGui::Indent(16.0f);

    ImGui::SeparatorText("Appearance");
    if (ImGui::RadioButton("Light", theme_index_ == 0)) {
        theme_index_ = 0;
    }
    ImGui::SameLine();
    if (ImGui::RadioButton("Dark", theme_index_ == 1)) {
        theme_index_ = 1;
    }

    ImGui::Spacing();
    ImGui::SeparatorText("Runtime");
    ImGui::SetNextItemWidth(220.0f * app_->dpi_scale());
    ImGui::InputInt("Reaction time (ms)", &reaction_time_ms_);
    reaction_time_ms_ = std::clamp(reaction_time_ms_, 0, 5000);

    ImGui::Spacing();
    ImGui::SeparatorText("Logging");
    ImGui::SetNextItemWidth(220.0f * app_->dpi_scale());
    if (ImGui::BeginCombo("Log level", kLogLevels[static_cast<std::size_t>(log_level_index_)])) {
        for (int index = 0; index < static_cast<int>(kLogLevels.size()); ++index) {
            const bool selected = index == log_level_index_;
            if (ImGui::Selectable(kLogLevels[static_cast<std::size_t>(index)], selected)) {
                log_level_index_ = index;
            }
            if (selected) {
                ImGui::SetItemDefaultFocus();
            }
        }
        ImGui::EndCombo();
    }
    text_muted("DEBUG log: see diagnostics.log");

    ImGui::Unindent(16.0f);
    ImGui::EndChild();

    ImGui::Indent(16.0f);
    if (!status_.empty()) {
        text_muted(status_);
    }
    ImGui::Spacing();
    if (ImGui::Button("Reload")) {
        reload();
    }
    ImGui::SameLine();
    ImGui::Dummy(ImVec2(ImGui::GetContentRegionAvail().x - 110.0f * app_->dpi_scale(), 0.0f));
    ImGui::SameLine();
    if (primary_button("Apply")) {
        save();
    }
    ImGui::Unindent(16.0f);
    ImGui::Dummy(ImVec2(0.0f, 8.0f));
}

void SettingsPage::save() {
    auto settings = app_->controller().settings();
    settings.log_level = kLogLevels[static_cast<std::size_t>(log_level_index_)];
    settings.reaction_time_ms = reaction_time_ms_;
    settings.theme = theme_index_ == 1 ? "dark" : "light";
    std::string error;
    app_->controller().save_settings(settings, &error);
    if (!error.empty()) {
        status_ = error;
        app_->notify(error, true);
        return;
    }
    status_ = "Settings saved.";
    app_->apply_theme(theme::mode_from_string(settings.theme));
    app_->notify("Settings saved.");
}

}  // namespace divergencesplitter::ui
