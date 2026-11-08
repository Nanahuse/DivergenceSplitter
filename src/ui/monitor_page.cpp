#include "monitor_page.hpp"
#include "monitor_row.hpp"

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
            instance_details_.erase(instance.index);
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
    std::erase_if(instance_details_, [&](int index) { return !live.contains(index); });
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
    ImGui::Separator();
    ImGui::Text("Instance %d", card.index);
    ImGui::SameLine();
    ImGui::TextColored(status_color(card.state, palette), "%s", card.status.c_str());
    ImGui::SameLine();
    ImGui::Text("| %.1f fps", card.evaluation_fps);
    ImGui::SameLine();
    if (ImGui::SmallButton("Inspect")) open_inspector(card);
    ImGui::SameLine();
    if (ImGui::SmallButton("Instance details")) {
        if (instance_details_.contains(card.index)) instance_details_.erase(card.index);
        else instance_details_.insert(card.index);
    }
    if (instance_details_.contains(card.index)) {
        ImGui::Text("%s | %s", card.endpoint.c_str(), card.timer_status.c_str());
        ImGui::Text("Evaluation: Avg %s | Max %s", card.average.c_str(), card.maximum.c_str());
        if (!card.action_status.empty()) text_muted(card.action_status);
    }
    if (!card.error.empty()) text_error_wrapped(card.error);
    if (!card.notice.empty()) ImGui::TextColored(palette.warning, "%s", card.notice.c_str());
    if (card.rule_groups.empty()) {
        for (const auto& group : card.groups)
            for (const auto& line : group.lines) ImGui::TextWrapped("%s", line.label.c_str());
    }
    const auto group_ui = [&](const MonitorRuleGroup& group) {
        ImGui::PushID(group.path.c_str());
        auto& was_current = current_groups_[card.index][group.path];
        if (group.current != was_current) ImGui::SetNextItemOpen(group.current, ImGuiCond_Always);
        was_current = group.current;
        const auto label = group.label + (group.current ? " | Current target" : " | History / inactive") + "###group";
        if (ImGui::CollapsingHeader(label.c_str(), group.current ? ImGuiTreeNodeFlags_DefaultOpen : 0))
            for (const auto& rule : group.rules) draw_rule(rule, card);
        ImGui::PopID();
    };
    for (const auto& group : card.rule_groups) if (group.current) group_ui(group);
    if (ImGui::CollapsingHeader("History / inactive rules"))
        for (const auto& group : card.rule_groups) if (!group.current) group_ui(group);
    if (!comparisons_[card.index].empty()) {
        const auto label = "Compare detectors (" + std::to_string(comparisons_[card.index].size()) + ")";
        if (ImGui::SmallButton(label.c_str())) {
            selected_instance_ = card.index;
            selected_identity_ = card.history ? card.history->identity : 0;
            comparison_details_ = true;
            comparison_view_ = {};
            details_open_ = true;
        }
    }
    ImGui::PopID();
}

void MonitorPage::draw_rule(const RuleDiagnosticsNode& rule, const ScenarioCardModel& card) {
    ImGui::PushID(rule.path.c_str());
    auto label = "Rule " + std::to_string(rule.index + 1);
    if (rule.action) label += " -> " + std::string{to_string(*rule.action)};

    if (!rule.sequence_rules.empty()) {
        const auto current = compact_sequence_rule(rule);
        label += current ? " | " + std::to_string(*rule.active_rule_index + 1) + " / " +
                           std::to_string(rule.sequence_rules.size()) : " | Complete";
        if (ImGui::CollapsingHeader(label.c_str(), ImGuiTreeNodeFlags_DefaultOpen)) {
            if (current) draw_rule(*current, card);
            else if (ImGui::Selectable("Complete - inspect rule history")) {
                const auto roots = inspector_rule_roots(card);
                for (const auto& root : roots) {
                    if (root.condition->path.starts_with(rule.path + ".")) {
                        select_condition(card, *root.condition);
                        break;
                    }
                }
            }
        }
    } else if (ImGui::CollapsingHeader(label.c_str(), ImGuiTreeNodeFlags_DefaultOpen)) {
        ImGui::PushStyleVar(ImGuiStyleVar_CellPadding, ImVec2(4 * app_->dpi_scale(), app_->dpi_scale()));
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(4 * app_->dpi_scale(), 2 * app_->dpi_scale()));
        if (ImGui::BeginTable("##conditions", 3, ImGuiTableFlags_SizingStretchProp)) {
            ImGui::TableSetupColumn("State", ImGuiTableColumnFlags_WidthFixed, 18 * app_->dpi_scale());
            ImGui::TableSetupColumn("Condition", ImGuiTableColumnFlags_WidthStretch);
            ImGui::TableSetupColumn("History", ImGuiTableColumnFlags_WidthFixed, 140 * app_->dpi_scale());
            draw_condition(rule.condition, card);
            ImGui::EndTable();
        }
        ImGui::PopStyleVar(2);
    }
    ImGui::PopID();
}

void MonitorPage::draw_condition(const ConditionDiagnosticsNode& node, const ScenarioCardModel& card,
                                  int depth, std::string_view role) {
    if (node.type.empty() || node.type == "none") return;
    const auto row = compact_condition_row(node);
    const auto children = compact_condition_children(row);
    const auto action = draw_compact_condition_row(row, !children.empty(), depth, role,
        details_open_ && selected_instance_ == card.index && selected_path_ == node.path,
        plots_[card.index].plots, draw_time_, window_seconds_, theme::colors(app_->theme_mode()), app_->dpi_scale());
    if (action.graph_visible && row.graph) requested_paths_[card.index].insert(row.graph->path);
    if (action.selected) select_condition(card, *action.selected);
    if (action.open)
        for (const auto& child : children) draw_condition(*child.condition, card, depth + 1, child.role);
}

void MonitorPage::open_inspector(const ScenarioCardModel& card) {
    const auto roots = inspector_rule_roots(card);
    for (const auto& root : roots)
        if (root.current) { select_condition(card, *root.condition); return; }
    if (!roots.empty()) select_condition(card, *roots.front().condition);
}

void MonitorPage::select_condition(const ScenarioCardModel& card, const ConditionDiagnosticsNode& node) {
    selected_instance_ = card.index;
    selected_path_ = node.path;
    selected_identity_ = card.history ? card.history->identity : 0;
    comparison_details_ = false;
    inspector_root_path_ = node.path;
    for (const auto& root : inspector_rule_roots(card))
        if (node.path == root.condition->path || node.path.starts_with(root.condition->path + "."))
            inspector_root_path_ = root.condition->path;
    inspector_selection_changed_ = true;
    detail_view_ = {};
    details_open_ = true;
}

void MonitorPage::draw_structure(const ConditionDiagnosticsNode& node, const ScenarioCardModel& card,
                                  const std::string& label, bool expand_selection) {
    ImGui::PushID(node.path.c_str());
    const bool children = !node.children.empty();
    auto flags = ImGuiTreeNodeFlags_OpenOnArrow | ImGuiTreeNodeFlags_SpanAvailWidth;
    if (!children) flags |= ImGuiTreeNodeFlags_Leaf;
    if (node.path == selected_path_) flags |= ImGuiTreeNodeFlags_Selected;
    if (node.path == inspector_root_path_) flags |= ImGuiTreeNodeFlags_DefaultOpen;
    if (expand_selection && (node.path == selected_path_ || selected_path_.starts_with(node.path + ".")))
        ImGui::SetNextItemOpen(true, ImGuiCond_Always);
    const bool open = ImGui::TreeNodeEx("##structure", flags, "%s", label.c_str());
    if (ImGui::IsItemClicked() && !ImGui::IsItemToggledOpen()) select_condition(card, node);
    if (open) {
        for (std::size_t i = 0; i < node.children.size(); ++i) {
            const auto& child = node.children[i];
            auto name = child.type;
            if (node.type == "then") {
                name = std::to_string(i + 1) + " - " + name;
                if (node.completed || i < node.active_step.value_or(0)) name += " (done)";
                else if (node.active_step == i) name += " (current)";
                else name += " (next)";
            } else if (node.type == "reset_when") name = (i == 0 ? "Condition - " : "Reset - ") + name;
            draw_structure(child, card, name, expand_selection);
        }
        ImGui::TreePop();
    }
    ImGui::PopID();
}

void MonitorPage::draw_details() {
    if (!details_open_) return;
    const ScenarioCardModel* card = nullptr;
    for (const auto& candidate : data_.cards)
        if (candidate.index == selected_instance_ && candidate.history && candidate.history->identity == selected_identity_)
            card = &candidate;
    if (!card) { details_open_ = false; return; }
    const float scale = app_->dpi_scale();
    ImGui::SetNextWindowSize(ImVec2(1040 * scale, 760 * scale), ImGuiCond_FirstUseEver);
    if (ImGui::Begin("History details", &details_open_)) {
        const auto palette = theme::colors(app_->theme_mode());
        ImGui::PushID(static_cast<int>(selected_identity_));
        ImGui::PushID(selected_instance_);
        ImGui::Text("Instance %d | %s | %s | %.1f fps", card->index, card->endpoint.c_str(), card->status.c_str(), card->evaluation_fps);
        ImGui::SameLine();
        if (ImGui::SmallButton(comparison_details_ ? "Conditions" : "Compare detectors")) {
            if (comparison_details_) open_inspector(*card);
            else {
                if (const auto* node = find_condition(*card, selected_path_); node && !node->detector_type.empty())
                    comparisons_[card->index].insert(node->path);
                comparison_details_ = true;
                comparison_view_.reset = true;
            }
        }
        ImGui::TextDisabled("%s | Avg %s | Max %s", card->timer_status.c_str(), card->average.c_str(), card->maximum.c_str());
        ImGui::Separator();
        ImGui::BeginChild("##structure", ImVec2(250 * scale, 0), true);
        if (comparison_details_) {
            ImGui::TextUnformatted("Detectors (current and past rules)");
            for (const auto& group : card->rule_groups) {
                bool heading = false;
                for (const auto& rule : group.rules) visit_rule(rule, [&](const auto& node) {
                    if (node.detector_type.empty()) return;
                    if (!heading) { ImGui::SeparatorText(group.label.c_str()); heading = true; }
                    ImGui::PushID(node.path.c_str());
                    bool compare = comparisons_[card->index].contains(node.path);
                    const auto label = node.detector_type + "##compare";
                    if (ImGui::Checkbox(label.c_str(), &compare)) {
                        if (compare) comparisons_[card->index].insert(node.path);
                        else comparisons_[card->index].erase(node.path);
                        comparison_view_.reset = true;
                    }
                    if (ImGui::IsItemHovered()) ImGui::SetTooltip("%s", node.path.c_str());
                    ImGui::PopID();
                });
            }
        } else {
            const auto roots = inspector_rule_roots(*card);
            std::string preview = inspector_root_path_;
            for (const auto& root : roots) if (root.condition->path == inspector_root_path_) preview = root.label;
            ImGui::SetNextItemWidth(-1);
            if (ImGui::BeginCombo("##rule", preview.c_str())) {
                for (const auto& root : roots) {
                    const auto label = root.label + (root.current ? " | Current" : " | History") + "##" + root.condition->path;
                    if (ImGui::Selectable(label.c_str(), root.condition->path == inspector_root_path_))
                        select_condition(*card, *root.condition);
                }
                ImGui::EndCombo();
            }
            const bool expand = inspector_selection_changed_;
            inspector_selection_changed_ = false;
            if (const auto* root = find_condition(*card, inspector_root_path_))
                draw_structure(*root, *card, root->type, expand);
        }
        ImGui::EndChild();
        ImGui::SameLine();
        ImGui::BeginChild("##history_content", ImVec2(0, 0));
        if (comparison_details_) {
            std::vector<const ConditionDiagnosticsNode*> nodes;
            for (const auto& group : card->rule_groups)
                for (const auto& rule : group.rules) visit_rule(rule, [&](const auto& node) {
                    if (comparisons_[card->index].contains(node.path)) {
                        nodes.push_back(&node);
                        requested_paths_[card->index].insert(node.path);
                    }
                });
            if (nodes.empty()) text_muted("Select detectors on the left.");
            else draw_detector_comparison(nodes, plots_[card->index].plots, draw_time_, window_seconds_,
                std::max(180 * scale, ImGui::GetContentRegionAvail().y - 40 * scale), palette, &comparison_view_);
        } else if (const auto* selected = find_condition(*card, selected_path_)) {
            requested_paths_[card->index].insert(selected->path);
            ImGui::PushID(selected_path_.c_str());
            ImGui::TextWrapped("%s", selected->description.c_str());
            ImGui::TextDisabled("%s | %s", condition_is_current(*card, selected_path_) ? "Current target" : "History / inactive", selected->status.c_str());
            if (selected->measurement.value)
                ImGui::Text("Value: %.4g %s", *selected->measurement.value, selected->measurement.unit.c_str());
            if (selected->measurement.target) {
                ImGui::SameLine();
                ImGui::Text("Target: %.4g %s", *selected->measurement.target, selected->measurement.unit.c_str());
            }
            if (selected->max_score) ImGui::Text("Maximum score: %.4g", *selected->max_score);
            if (!selected->detector_type.empty()) {
                bool compare = comparisons_[card->index].contains(selected_path_);
                if (ImGui::Checkbox("Include in detector comparison", &compare)) {
                    if (compare) comparisons_[card->index].insert(selected_path_);
                    else comparisons_[card->index].erase(selected_path_);
                    comparison_view_.reset = true;
                }
            }
            const float plot_space = std::max(260 * scale, ImGui::GetContentRegionAvail().y - 90 * scale);
            draw_history_plot("History", *selected, plots_[card->index].plots, draw_time_, window_seconds_,
                             plot_space * 0.65f, palette, true, false, &detail_view_);
            draw_history_plot("Result timeline", *selected, plots_[card->index].plots, draw_time_, window_seconds_,
                             plot_space * 0.35f, palette, true, true, &detail_view_);
            text_muted("Blank: unmeasured | Yellow: reset | Green: transition | Red: error");
            ImGui::PopID();
        }
        ImGui::EndChild();
        ImGui::PopID();
        ImGui::PopID();
    }
    ImGui::End();
}
} // namespace divergencesplitter::ui
