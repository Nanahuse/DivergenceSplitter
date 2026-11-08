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

[[nodiscard]] std::string state_text(InstanceState state);
[[nodiscard]] std::string phase_text(TimerPhase phase);
[[nodiscard]] std::string latency_text(double milliseconds, bool measured);
[[nodiscard]] std::vector<EvaluationGroup> evaluation_groups(
    const InstanceDiagnosticsSnapshot& instance
);
[[nodiscard]] std::string scenario_overview(const ScenarioDiagnosticsSnapshot& scenario);
[[nodiscard]] ScenarioCardModel card_model(const InstanceDiagnosticsSnapshot& instance);

}  // namespace divergencesplitter::ui
