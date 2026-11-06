#pragma once

#include <string>
#include <vector>

#include "divergencesplitter/runtime/diagnostics.hpp"

namespace divergencesplitter::ui {

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

struct ScenarioCardModel {
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
