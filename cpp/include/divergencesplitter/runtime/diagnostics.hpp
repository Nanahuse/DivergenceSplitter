#pragma once

#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "divergencesplitter/rule/rule.hpp"
#include "divergencesplitter/runtime/models.hpp"

namespace divergencesplitter {

struct ConditionDiagnosticsNode {
    std::string path;
    std::string type;
    std::string status;
    std::string description;
    std::string detector_type;
    std::optional<double> latest_score;
    std::optional<double> max_score;
    std::optional<double> minimum_score;
    std::vector<ConditionDiagnosticsNode> children;
};

struct RuleDiagnosticsNode {
    std::string path;
    std::size_t index{};
    std::string type;
    std::optional<ActionOperation> action;
    std::optional<std::size_t> active_rule_index;
    ConditionDiagnosticsNode condition;
    std::vector<RuleDiagnosticsNode> sequence_rules;
};

struct RuleGroupDiagnostics {
    std::string name;
    std::vector<RuleDiagnosticsNode> rules;
};

struct SplitDiagnosticsNode {
    std::string path;
    std::size_t index{};
    bool configured{};
    std::vector<RuleDiagnosticsNode> rules;
};

struct ScenarioDiagnosticsSnapshot {
    std::optional<LiveSplitSnapshot> snapshot;
    bool configuration_valid{true};
    std::optional<ActionOperation> pending_action;
    std::vector<RuleGroupDiagnostics> start;
    std::vector<RuleGroupDiagnostics> reset;
    std::vector<RuleGroupDiagnostics> incomplete;
    std::vector<SplitDiagnosticsNode> splits;
    std::uint64_t evaluation_count{};
    double last_evaluation_ms{};
    std::uint64_t rule_errors{};
};

enum class InstanceState {
    connecting,
    ready,
    failed,
    stopped,
};

[[nodiscard]] std::string_view to_string(InstanceState state) noexcept;

struct InstanceDiagnosticsSnapshot {
    int index{};
    InstanceState state{InstanceState::connecting};
    std::string error;
    std::optional<RunInfo> run;
    std::uint64_t generation{};
    std::uint64_t action_count{};
    std::optional<ActionOperation> last_action;
    std::string last_action_result;
    std::optional<ScenarioDiagnosticsSnapshot> scenario;
};

}  // namespace divergencesplitter
