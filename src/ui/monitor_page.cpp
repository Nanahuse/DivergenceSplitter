#include "monitor_page.hpp"

#include <imgui.h>
#include <algorithm>
#include <cstdio>
#include <functional>

#include "app.hpp"
#include "theme.hpp"
#include "ui_helpers.hpp"

namespace divergencesplitter::ui {
namespace {
void visit_condition(const ConditionDiagnosticsNode& node, const std::function<void(const ConditionDiagnosticsNode&)>& fn) {
    fn(node);
    for (const auto& child : node.children) visit_condition(child, fn);
}
void visit_rule(const RuleDiagnosticsNode& rule, const std::function<void(const ConditionDiagnosticsNode&)>& fn) {
    visit_condition(rule.condition, fn);
    for (const auto& child : rule.sequence_rules) visit_rule(child, fn);
}
ImVec4 status_color(InstanceState state, const theme::Colors& palette) {
    switch (state) {
        case InstanceState::ready: return palette.ready;
        case InstanceState::connecting: return palette.connecting;
        case InstanceState::failed: return palette.failed;
        case InstanceState::stopped: return palette.stopped;
    }
    return palette.muted;
}
}

MonitorPage::MonitorPage(App* app) : app_(app) {}

void MonitorPage::update(double now) {
    if (now < next_update_) return;
    next_update_ = now + 0.1;
    const auto& session = app_->controller().session();
    const auto capture = session.capture_stats();
    data_.running = capture.running;
    data_.frames_published = capture.frames_published;
    data_.measured_fps = capture.measured_fps;
    data_.last_error = app_->controller().last_error();
    if (preview_visible_) {
        const auto preview = session.latest_preview();
        if (preview && !preview->empty()) preview_.update(app_->device(), app_->context(), *preview);
        else preview_.clear();
    }
    const auto instances = session.instance_diagnostics(true, &requested_paths_);
    const auto profile = session.profile();
    const double sampled_at = monotonic_now().nanoseconds / 1e9;
    data_.cards.clear();
    std::set<int> live;
    for (const auto& instance : instances) {
        live.insert(instance.index);
        const auto count = instance.scenario ? instance.scenario->evaluation_count : 0;
        const auto history = instance.scenario ? instance.scenario->history : nullptr;
        const auto identity = history ? history->identity : 0;
        auto& rate = evaluation_rates_[instance.index];
        rate.update(identity, count, sampled_at);
        auto card = card_model(instance);
        card.evaluation_fps = rate.fps();
        if (instance.index >= 0 && static_cast<std::size_t>(instance.index) < profile.instances.size())
            card.endpoint = "localhost:" + std::to_string(profile.instances[static_cast<std::size_t>(instance.index)].connection.port);
        auto& plots = plots_[instance.index];
        if (plots.identity != identity) {
            comparisons_.erase(instance.index);
            current_groups_.erase(instance.index);
            if (selected_instance_ == instance.index) details_open_ = false;
        }
        std::set<std::string> holds;
        for (const auto& group : card.rule_groups)
            for (const auto& rule : group.rules)
                visit_rule(rule, [&](const auto& node) { if (node.type == "hold") holds.insert(node.path); });
        plots = {identity, history ? prepare_history(*history, holds) : HistoryPlots{}};
        data_.cards.push_back(std::move(card));
    }
    std::erase_if(evaluation_rates_, [&](const auto& entry) { return !live.contains(entry.first); });
    std::erase_if(plots_, [&](const auto& entry) { return !live.contains(entry.first); });
    std::erase_if(comparisons_, [&](const auto& entry) { return !live.contains(entry.first); });
    std::erase_if(current_groups_, [&](const auto& entry) { return !live.contains(entry.first); });
    std::erase_if(requested_paths_, [&](const auto& entry) { return !live.contains(entry.first); });
    if (!live.contains(selected_instance_)) details_open_ = false;
}

void MonitorPage::draw() {
    draw_time_ = monotonic_now().nanoseconds / 1e9;
    requested_paths_.clear();
    const float scale = app_->dpi_scale();
    ImGui::BeginChild("##monitor", ImVec2(0, 0));
    text_section_title("Global Status");
    draw_status_rows();
    ImGui::Separator();
    if (ImGui::CollapsingHeader("Input Preview")) {
        preview_visible_ = true;
        image_fit(preview_, 240 * scale, "No input");
    } else preview_visible_ = false;
    if (!data_.last_error.empty()) text_error_wrapped(data_.last_error);
    ImGui::Spacing();
    text_section_title("Instances");
    ImGui::SameLine();
    draw_reset_button();
    ImGui::TextUnformatted("History");
    for (const int seconds : {15, 30, 60}) {
        ImGui::SameLine();
        const auto label = std::to_string(seconds) + " s";
        if (ImGui::RadioButton(label.c_str(), window_seconds_ == seconds)) window_seconds_ = seconds;
    }
    draw_cards();
    ImGui::EndChild();
    draw_details();
}

void MonitorPage::draw_status_rows() {
    const auto palette = theme::colors(app_->theme_mode());
    ImGui::TextColored(data_.running ? palette.active : palette.stopped, "Capture: %s", data_.running ? "Running" : "Stopped");
    ImGui::SameLine();
    ImGui::Text(" | Input: %.1f fps | %llu frames", data_.measured_fps, static_cast<unsigned long long>(data_.frames_published));
    for (const auto& card : data_.cards) {
        ImGui::Text("Instance %d evaluation: %.1f fps", card.index, card.evaluation_fps);
    }
}

void MonitorPage::draw_cards() {
    if (data_.cards.empty()) text_muted("No instances are running.");
    for (const auto& card : data_.cards) draw_card(card);
}

void MonitorPage::draw_reset_button() {
    const double now = ImGui::GetTime();
    const float scale = app_->dpi_scale();
    // Keep the ImGui widget ID stable while the visible label counts down.
    std::string label = "Reset All###reset_all";
    if (reset_holding_) {
        const double remaining = std::max(0.0, 2.0 - (now - reset_started_));
        char text[64]{};
        std::snprintf(text, sizeof(text), "Hold... %.1f s###reset_all", remaining);
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
    ImGui::PushID(card.index);
    const auto title = "Instance " + std::to_string(card.index) + " | " + card.endpoint;
    ImGui::Spacing();
    ImGui::SeparatorText(title.c_str());
    ImGui::TextColored(status_color(card.state, palette), "%s", card.status.c_str());
    ImGui::SameLine();
    ImGui::Text(" | %s | Evaluation %.1f fps | Avg %s | Max %s",
                card.timer_status.c_str(), card.evaluation_fps, card.average.c_str(), card.maximum.c_str());
    if (!card.error.empty()) text_error_wrapped(card.error);
    if (!card.notice.empty()) ImGui::TextColored(palette.warning, "%s", card.notice.c_str());
    if (!card.action_status.empty()) text_muted(card.action_status);
    if (card.rule_groups.empty()) {
        for (const auto& group : card.groups)
            for (const auto& line : group.lines) ImGui::TextWrapped("%s", line.label.c_str());
    }
    for (const auto& group : card.rule_groups) {
        ImGui::PushID(group.path.c_str());
        auto& was_current = current_groups_[card.index][group.path];
        if (group.current != was_current) ImGui::SetNextItemOpen(group.current, ImGuiCond_Always);
        was_current = group.current;
        const auto label = group.label + (group.current ? " | Current target" : " | History / inactive") + "###group";
        if (ImGui::CollapsingHeader(label.c_str(), group.current ? ImGuiTreeNodeFlags_DefaultOpen : 0))
            for (const auto& rule : group.rules) draw_rule(rule, card);
        ImGui::PopID();
    }
    if (!comparisons_[card.index].empty() && card.history) {
        std::vector<const ConditionDiagnosticsNode*> selected;
        for (const auto& group : card.rule_groups)
            for (const auto& rule : group.rules)
                visit_rule(rule, [&](const auto& node) {
                    if (comparisons_[card.index].contains(node.path)) selected.push_back(&node);
                });
        if (!selected.empty() && ImGui::CollapsingHeader("Detector comparison", ImGuiTreeNodeFlags_DefaultOpen)) {
            if (ImGui::IsRectVisible(ImVec2(ImGui::GetContentRegionAvail().x, 230 * scale)))
                for (const auto* node : selected) requested_paths_[card.index].insert(node->path);
            if (draw_detector_comparison(selected, plots_[card.index].plots, draw_time_,
                                         window_seconds_, 230 * scale, palette)) {
                selected_instance_ = card.index;
                selected_identity_ = card.history->identity;
                comparison_details_ = true;
                comparison_view_ = {};
                details_open_ = true;
            }
        }
    }
    ImGui::PopID();
}

void MonitorPage::draw_rule(const RuleDiagnosticsNode& rule, const ScenarioCardModel& card) {
    ImGui::PushID(rule.path.c_str());
    auto label = "Rule " + std::to_string(rule.index + 1);
    if (rule.action) label += " -> " + std::string{to_string(*rule.action)};
    if (rule.active_rule_index) label += " | active " + std::to_string(*rule.active_rule_index + 1);
    if (ImGui::CollapsingHeader(label.c_str(), ImGuiTreeNodeFlags_DefaultOpen)) {
        if (!rule.sequence_rules.empty()) {
            for (const auto& child : rule.sequence_rules) draw_rule(child, card);
        } else draw_condition(rule.condition, card);
    }
    ImGui::PopID();
}

void MonitorPage::draw_condition(const ConditionDiagnosticsNode& node, const ScenarioCardModel& card) {
    if (node.type.empty() || node.type == "none") return;
    const auto palette = theme::colors(app_->theme_mode());
    const float scale = app_->dpi_scale();
    ImGui::PushID(node.path.c_str());
    const auto label = node.description + " [" + node.status + "]";
    if (ImGui::Selectable(label.c_str(), details_open_ && selected_instance_ == card.index && selected_path_ == node.path)) {
        select_condition(card, node);
    }
    if (!node.detector_type.empty()) {
        bool compare = comparisons_[card.index].contains(node.path);
        if (ImGui::Checkbox("Compare detector", &compare)) {
            if (compare) comparisons_[card.index].insert(node.path);
            else comparisons_[card.index].erase(node.path);
        }
    }
    if (node.measurement.value) {
        ImGui::Text("%s: %.4g %s", node.status == "skipped" ? "Last value" : "Value",
                    *node.measurement.value, node.measurement.unit.c_str());
        if (node.measurement.target) {
            ImGui::SameLine();
            ImGui::TextColored(palette.warning, " / Target %.4g", *node.measurement.target);
        }
    } else if (node.measurement.target) ImGui::Text("Target: %.4g %s", *node.measurement.target, node.measurement.unit.c_str());
    const float plot_height = 64 * scale;
    if (ImGui::IsRectVisible(ImVec2(ImGui::GetContentRegionAvail().x, plot_height)))
        requested_paths_[card.index].insert(node.path);
    if (draw_history_plot("##history", node, plots_[card.index].plots,
                          draw_time_, window_seconds_, plot_height, palette)) select_condition(card, node);
    if (!node.children.empty()) {
        ImGui::Indent(18 * scale);
        for (const auto& child : node.children) draw_condition(child, card);
        ImGui::Unindent(18 * scale);
    }
    ImGui::PopID();
}

void MonitorPage::select_condition(const ScenarioCardModel& card, const ConditionDiagnosticsNode& node) {
    selected_instance_ = card.index;
    selected_path_ = node.path;
    selected_identity_ = card.history ? card.history->identity : 0;
    comparison_details_ = false;
    detail_view_ = {};
    details_open_ = true;
}

void MonitorPage::draw_details() {
    if (!details_open_) return;
    const ConditionDiagnosticsNode* selected = nullptr;
    const ScenarioCardModel* card = nullptr;
    bool selected_current = false;
    for (const auto& candidate : data_.cards) {
        if (candidate.index != selected_instance_ || !candidate.history || candidate.history->identity != selected_identity_) continue;
        card = &candidate;
        selected = find_condition(candidate, selected_path_);
        for (const auto& group : candidate.rule_groups)
            if (selected_path_.starts_with(group.path + ".")) selected_current = group.current;
    }
    if (!card || (!comparison_details_ && !selected)) { details_open_ = false; return; }
    if (!comparison_details_) requested_paths_[card->index].insert(selected->path);
    ImGui::SetNextWindowSize(ImVec2(800 * app_->dpi_scale(), 700 * app_->dpi_scale()), ImGuiCond_FirstUseEver);
    if (ImGui::Begin("History details", &details_open_)) {
        const auto palette = theme::colors(app_->theme_mode());
        ImGui::PushID(static_cast<int>(selected_identity_));
        ImGui::PushID(selected_instance_);
        ImGui::PushID(comparison_details_ ? "comparison" : selected_path_.c_str());
        if (comparison_details_) {
            std::vector<const ConditionDiagnosticsNode*> nodes;
            for (const auto& group : card->rule_groups)
                for (const auto& rule : group.rules)
                    visit_rule(rule, [&](const auto& node) {
                        if (comparisons_[card->index].contains(node.path)) {
                            nodes.push_back(&node);
                            requested_paths_[card->index].insert(node.path);
                        }
                    });
            ImGui::Text("Instance %d | Detector comparison", card->index);
            draw_detector_comparison(nodes, plots_[card->index].plots, draw_time_, window_seconds_,
                                     420 * app_->dpi_scale(), palette, &comparison_view_);
        } else {
            ImGui::Text("Instance %d | %s", card->index, selected->path.c_str());
            ImGui::TextDisabled("%s", selected_current ? "Current target" : "History / inactive");
            ImGui::TextWrapped("%s [%s]", selected->description.c_str(), selected->status.c_str());
            if (selected->measurement.value) ImGui::Text("%s: %.4g %s", selected->status == "skipped" ? "Last value" : "Value", *selected->measurement.value, selected->measurement.unit.c_str());
            if (selected->measurement.target) ImGui::Text("Target: %.4g %s", *selected->measurement.target, selected->measurement.unit.c_str());
            const double now = draw_time_;
            draw_history_plot("History", *selected, plots_[card->index].plots, now, window_seconds_, 260 * app_->dpi_scale(), palette, true, false, &detail_view_);
            draw_history_plot("Result timeline", *selected, plots_[card->index].plots, now, window_seconds_, 180 * app_->dpi_scale(), palette, true, true, &detail_view_);
            text_muted("Blank = not measured | Reset: yellow | Transition: green | Error: red");
        }
        ImGui::PopID();
        ImGui::PopID();
        ImGui::PopID();
    }
    ImGui::End();
}
} // namespace divergencesplitter::ui
