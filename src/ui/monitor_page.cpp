#include "monitor_page.hpp"

#include <imgui.h>

#include <algorithm>
#include <cstdio>
#include <string>

#include "app.hpp"
#include "theme.hpp"
#include "ui_helpers.hpp"

namespace divergencesplitter::ui {
namespace {

ImVec4 status_color(InstanceState state, const theme::Colors& palette) {
    switch (state) {
        case InstanceState::ready:
            return palette.ready;
        case InstanceState::connecting:
            return palette.connecting;
        case InstanceState::failed:
            return palette.failed;
        case InstanceState::stopped:
            return palette.stopped;
    }
    return palette.muted;
}

int line_count(const ScenarioCardModel& card) {
    int count = 0;
    for (const auto& group : card.groups) {
        if (!group.label.empty()) {
            ++count;
        }
        count += static_cast<int>(group.lines.size());
    }
    return count;
}

int group_label_count(const ScenarioCardModel& card) {
    int count = 0;
    for (const auto& group : card.groups) {
        if (!group.label.empty()) {
            ++count;
        }
    }
    return count;
}

}  // namespace

MonitorPage::MonitorPage(App* app) : app_(app) {}

void MonitorPage::update(double now) {
    if (now < next_update_) {
        return;
    }
    next_update_ = now + 0.1;

    const auto& session = app_->controller().session();
    data_.running = session.running();
    const auto capture = session.capture_stats();
    data_.frames_published = capture.frames_published;
    data_.measured_fps = capture.measured_fps;
    data_.last_error = app_->controller().last_error();

    const auto preview = session.latest_preview();
    if (preview && !preview->empty()) {
        preview_.update(app_->device(), app_->context(), *preview);
    } else {
        preview_.clear();
    }

    const auto instances = session.instance_diagnostics();
    if (instances.empty()) {
        evaluation_rates_.clear();
    }
    const auto sampled_at = std::chrono::steady_clock::now();
    double processing_fps = 0.0;
    for (const auto& instance : instances) {
        const auto count = instance.scenario ? instance.scenario->evaluation_count : 0;
        auto [rate_it, inserted] = evaluation_rates_.try_emplace(
            instance.index, EvaluationRate{instance.generation, count, sampled_at, 0.0}
        );
        auto& rate = rate_it->second;
        if (rate.generation != instance.generation || count < rate.count) {
            rate = EvaluationRate{instance.generation, count, sampled_at, 0.0};
        }
        const double elapsed =
            std::chrono::duration<double>(sampled_at - rate.sampled_at).count();
        if (!inserted && elapsed >= 0.5) {
            rate.fps = static_cast<double>(count - rate.count) / elapsed;
            rate.count = count;
            rate.sampled_at = sampled_at;
        }
        processing_fps += rate.fps;
    }
    data_.processing_fps = processing_fps;

    data_.cards.clear();
    data_.cards.reserve(instances.size());
    for (const auto& instance : instances) {
        data_.cards.push_back(card_model(instance));
    }
}

void MonitorPage::draw() {
    const float scale = app_->dpi_scale();
    const float left_width = 380.0f * scale;

    ImGui::BeginChild("##monitor_left", ImVec2(left_width, 0.0f), false);
    ImGui::Indent(12.0f * scale);
    ImGui::Dummy(ImVec2(0.0f, 8.0f * scale));
    text_section_title("Global Status");
    draw_status_rows();

    ImGui::Dummy(ImVec2(0.0f, 8.0f * scale));
    text_section_title("Input Preview");
    image_fit(preview_, 300.0f * scale, "No input");
    ImGui::PushStyleColor(ImGuiCol_Text, ImGui::GetStyle().Colors[ImGuiCol_TextDisabled]);
    ImGui::Text(
        "Input: %llu frames  |  %s",
        static_cast<unsigned long long>(data_.frames_published),
        data_.running ? "running" : "stopped"
    );
    ImGui::PopStyleColor();

    if (!data_.last_error.empty()) {
        ImGui::Dummy(ImVec2(0.0f, 8.0f * scale));
        text_error_wrapped(data_.last_error);
    }
    ImGui::Unindent(12.0f * scale);
    ImGui::EndChild();

    ImGui::SameLine(0.0f, 0.0f);
    ImGui::BeginChild("##monitor_right", ImVec2(0.0f, 0.0f), false);
    ImGui::Indent(12.0f * scale);
    ImGui::Dummy(ImVec2(0.0f, 8.0f * scale));

    text_section_title("Scenario Overview");
    const float button_width = 130.0f * scale;
    ImGui::SameLine();
    ImGui::Dummy(ImVec2(
        std::max(0.0f, ImGui::GetContentRegionAvail().x - button_width),
        0.0f
    ));
    ImGui::SameLine();
    draw_reset_button();

    ImGui::Dummy(ImVec2(0.0f, 4.0f * scale));
    ImGui::BeginChild("##scenario_cards", ImVec2(0.0f, 0.0f), false);
    draw_cards();
    ImGui::EndChild();
    ImGui::Unindent(12.0f * scale);
    ImGui::EndChild();
}

void MonitorPage::draw_status_rows() {
    const auto palette = theme::colors(app_->theme_mode());
    const float scale = app_->dpi_scale();
    const auto row = [&](const char* label, const std::string& value, const ImVec4& color) {
        ImGui::PushStyleColor(ImGuiCol_Text, palette.text_secondary);
        ImGui::TextUnformatted(label);
        ImGui::PopStyleColor();
        ImGui::SameLine(130.0f * scale);
        ImGui::PushStyleColor(ImGuiCol_Text, color);
        ImGui::TextUnformatted(value.c_str());
        ImGui::PopStyleColor();
    };

    row("State", data_.running ? "Running" : "Stopped",
        data_.running ? palette.active : palette.stopped);
    char input_fps[64]{};
    if (data_.frames_published > 0) {
        std::snprintf(input_fps, sizeof(input_fps), "%.1f fps", data_.measured_fps);
    } else {
        std::snprintf(input_fps, sizeof(input_fps), "- fps");
    }
    row("Input FPS", input_fps, palette.text);
    char fps[64]{};
    std::snprintf(fps, sizeof(fps), "%.1f fps", data_.processing_fps);
    row(
        "Processing FPS",
        data_.cards.empty() ? "- fps" : fps,
        palette.text
    );
}

void MonitorPage::draw_cards() {
    if (data_.cards.empty()) {
        text_muted("No scenarios are running.");
        return;
    }
    for (const auto& card : data_.cards) {
        draw_card(card);
    }
}

void MonitorPage::draw_reset_button() {
    const double now = ImGui::GetTime();
    const float scale = app_->dpi_scale();
    std::string label = "Reset All";
    if (reset_holding_) {
        const double remaining = std::max(0.0, 2.0 - (now - reset_started_));
        char text[64]{};
        std::snprintf(text, sizeof(text), "Hold... %.1f s", remaining);
        label = text;
    }
    if (ImGui::Button(label.c_str(), ImVec2(130.0f * scale, 34.0f * scale))) {
        // A completed hold performs the reset below.
    }
    if (ImGui::IsItemActivated()) {
        reset_holding_ = true;
        reset_triggered_ = false;
        reset_started_ = now;
    }
    if (reset_holding_) {
        if (!ImGui::IsItemActive() || !ImGui::IsItemHovered()) {
            reset_holding_ = false;
            reset_triggered_ = false;
        } else if (!reset_triggered_ && now - reset_started_ >= 2.0) {
            reset_triggered_ = true;
            app_->controller().request_reset_all();
            app_->notify("Manual reset requested for all scenarios.");
        }
    }
}

void MonitorPage::draw_card(const ScenarioCardModel& card) {
    const auto palette = theme::colors(app_->theme_mode());
    const float scale = app_->dpi_scale();
    const int lines = line_count(card);
    const int labels = group_label_count(card);
    const float height =
        (72.0f + static_cast<float>(lines) * 18.0f +
         static_cast<float>(labels) * 20.0f + 20.0f) * scale;

    const std::string child_id = "##scenario_" + std::to_string(card.index);
    ImGui::PushStyleColor(ImGuiCol_ChildBg, palette.surface);
    ImGui::BeginChild(child_id.c_str(), ImVec2(0.0f, height), true);
    ImGui::PopStyleColor();
    ImGui::Indent(10.0f * scale);

    const std::string title = "Scenario " + std::to_string(card.index);
    ImGui::PushStyleColor(ImGuiCol_Text, palette.text);
    ImGui::TextUnformatted(title.c_str());
    ImGui::PopStyleColor();

    const std::string status = "\xE2\x97\x8F " + card.status;
    const float status_width = ImGui::CalcTextSize(status.c_str()).x;
    ImGui::SameLine();
    ImGui::Dummy(ImVec2(
        std::max(0.0f, ImGui::GetContentRegionAvail().x - status_width),
        0.0f
    ));
    ImGui::SameLine();
    ImGui::PushStyleColor(ImGuiCol_Text, status_color(card.state, palette));
    ImGui::TextUnformatted(status.c_str());
    ImGui::PopStyleColor();
    if (!card.error.empty() && ImGui::IsItemHovered()) {
        ImGui::SetTooltip("%s", card.error.c_str());
    }

    text_muted("Evaluating");
    if (card.groups.empty()) {
        text_muted("-");
    } else {
        for (const auto& group : card.groups) {
            if (!group.label.empty()) {
                ImGui::Dummy(ImVec2(0.0f, 2.0f * scale));
                ImGui::PushStyleColor(ImGuiCol_Text, palette.text);
                ImGui::TextUnformatted(group.label.c_str());
                ImGui::PopStyleColor();
            }
            for (const auto& line : group.lines) {
                ImGui::Indent(static_cast<float>(line.depth) * 14.0f * scale);
                if (line.strong) {
                    ImGui::PushStyleColor(ImGuiCol_Text, palette.text);
                }
                ImGui::TextUnformatted(line.label.c_str());
                if (line.strong) {
                    ImGui::PopStyleColor();
                }
                if (!line.detail.empty()) {
                    ImGui::SameLine();
                    text_muted(line.detail);
                }
                ImGui::Unindent(static_cast<float>(line.depth) * 14.0f * scale);
            }
        }
    }

    ImGui::Dummy(ImVec2(0.0f, 2.0f * scale));
    ImGui::Separator();
    text_muted("Evaluation");
    ImGui::SameLine(110.0f * scale);
    text_muted("Avg");
    ImGui::SameLine();
    ImGui::TextUnformatted(card.average.c_str());
    ImGui::SameLine();
    text_muted("Max");
    ImGui::SameLine();
    ImGui::TextUnformatted(card.maximum.c_str());

    ImGui::Unindent(10.0f * scale);
    ImGui::EndChild();
    ImGui::Dummy(ImVec2(0.0f, 4.0f * scale));
}

}  // namespace divergencesplitter::ui
