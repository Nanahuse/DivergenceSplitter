#pragma once

#include <string>
#include <vector>

#include "divergencesplitter/runtime/diagnostics.hpp"

namespace divergencesplitter::ui {

struct MonitorEvaluationRate {
    void update(std::uint64_t identity, std::uint64_t count, double now);
    [[nodiscard]] double fps() const noexcept { return fps_; }
private:
    std::uint64_t identity_{};
    std::uint64_t count_{};
    double sampled_at_{};
    double fps_{};
    bool initialized_{};
};

struct EvaluationLine {
    std::string label;
    std::string detail;
    int depth{};
    bool strong{};
};

struct EvaluationGroup {
    std::string label;
    std::vector<EvaluationLine> lines;
};

struct MonitorRuleGroup {
    std::string label;
    std::vector<RuleDiagnosticsNode> rules;
    std::string path;
    bool current{};
};

struct ScenarioCardModel {
    std::vector<MonitorRuleGroup> rule_groups;
    std::shared_ptr<const EvaluationHistorySnapshot> history;
    std::string timer_status;
    std::string notice;
    std::string action_status;
    std::string endpoint;
    double evaluation_fps{};
    int index{};
    InstanceState state{InstanceState::connecting};
    bool has_state{};
    std::string status;
    std::string error;
    std::vector<EvaluationGroup> groups;
    std::string average;
    std::string maximum;
};

struct CompactConditionRow {
    const ConditionDiagnosticsNode* anchor{};
    const ConditionDiagnosticsNode* graph{};
    const ConditionDiagnosticsNode* branch{};
    std::string label;
};

struct CompactConditionChild {
    const ConditionDiagnosticsNode* condition{};
    std::string role;
};

struct CurrentMonitorGroup {
    const MonitorRuleGroup* source{};
    std::string label;
};
[[nodiscard]] std::vector<CurrentMonitorGroup> current_monitor_groups(const ScenarioCardModel& card);
[[nodiscard]] int monitor_card_columns(float available_width, float scale, std::size_t count);

[[nodiscard]] CompactConditionRow compact_condition_row(const ConditionDiagnosticsNode& node);
[[nodiscard]] std::vector<CompactConditionChild> compact_condition_children(const CompactConditionRow& row);
[[nodiscard]] const RuleDiagnosticsNode* compact_sequence_rule(const RuleDiagnosticsNode& rule);

struct InspectorRuleRoot {
    const ConditionDiagnosticsNode* condition{};
    std::string label;
    bool current{};
};
[[nodiscard]] std::vector<InspectorRuleRoot> inspector_rule_roots(const ScenarioCardModel& card);
[[nodiscard]] bool condition_is_current(const ScenarioCardModel& card, std::string_view path);

[[nodiscard]] std::string state_text(InstanceState state);
[[nodiscard]] std::string phase_text(TimerPhase phase);
[[nodiscard]] std::string latency_text(double milliseconds, bool measured);
[[nodiscard]] std::vector<EvaluationGroup> evaluation_groups(
    const InstanceDiagnosticsSnapshot& instance
);
[[nodiscard]] std::string scenario_overview(const ScenarioDiagnosticsSnapshot& scenario);
[[nodiscard]] ScenarioCardModel card_model(const InstanceDiagnosticsSnapshot& instance);
[[nodiscard]] const ConditionDiagnosticsNode* find_condition(
    const ScenarioCardModel& card, std::string_view path);

}  // namespace divergencesplitter::ui
