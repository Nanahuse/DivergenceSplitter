#include "monitor_model.hpp"

#include <algorithm>
#include <iomanip>
#include <optional>
#include <sstream>

namespace divergencesplitter::ui {
namespace {

std::string score_text(const std::optional<double>& value) {
    if (!value.has_value()) {
        return "-";
    }
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(4) << *value;
    return stream.str();
}

std::string segment_name(const InstanceDiagnosticsSnapshot& instance, std::size_t index) {
    if (!instance.run.has_value()) {
        return {};
    }
    for (const auto& segment : instance.run->segments) {
        if (segment.index == static_cast<int>(index)) {
            return segment.name;
        }
    }
    return {};
}

std::string condition_detail(const ConditionDiagnosticsNode& node) {
    if (!node.detector_type.empty()) {
        std::string detail = node.detector_type + "   " + score_text(node.latest_score) +
                             " / " + score_text(node.minimum_score) + "   Max: " +
                             score_text(node.max_score);
        if (node.status == "error") {
            detail = "ERROR   " + detail;
        }
        return detail;
    }
    if (!node.description.empty() && node.description != node.type) {
        return node.description;
    }
    return {};
}

bool is_visible_condition(const ConditionDiagnosticsNode& node) {
    if (node.type.empty() || node.type == "none") {
        return false;
    }
    if (node.status == "true" || node.status == "false" || node.status == "error") {
        return true;
    }
    return std::any_of(node.children.begin(), node.children.end(), is_visible_condition);
}

void append_condition(
    const ConditionDiagnosticsNode& node,
    int depth,
    std::vector<EvaluationLine>& lines
) {
    if (node.type.empty() || node.type == "none") {
        for (const auto& child : node.children) {
            append_condition(child, depth, lines);
        }
        return;
    }
    if (node.status == "true" || node.status == "false" || node.status == "error") {
        std::string label = node.type;
        if (!node.status.empty()) {
            label += " [" + node.status + "]";
        }
        lines.push_back(EvaluationLine{label, condition_detail(node), depth, false});
    }
    for (const auto& child : node.children) {
        append_condition(child, depth + 1, lines);
    }
}

void append_rules(
    const std::vector<RuleDiagnosticsNode>& rules,
    int depth,
    std::vector<EvaluationLine>& lines
) {
    for (const auto& rule : rules) {
        if (!rule.sequence_rules.empty()) {
            if (rule.active_rule_index.has_value() &&
                *rule.active_rule_index < rule.sequence_rules.size()) {
                append_rules({rule.sequence_rules[*rule.active_rule_index]}, depth, lines);
            }
            continue;
        }
        std::string label = "Rule " + std::to_string(rule.index);
        if (rule.action.has_value()) {
            label += " -> " + std::string{to_string(*rule.action)};
        }
        lines.push_back(EvaluationLine{label, {}, depth, true});
        if (is_visible_condition(rule.condition)) {
            append_condition(rule.condition, depth + 1, lines);
        }
    }
}

void append_group(
    const std::vector<RuleGroupDiagnostics>& groups,
    const std::string& label,
    int depth,
    std::vector<EvaluationGroup>& result
) {
    EvaluationGroup group;
    group.label = label;
    for (const auto& source : groups) {
        append_rules(source.rules, depth + 1, group.lines);
    }
    if (!group.lines.empty()) {
        result.push_back(std::move(group));
    }
}

}  // namespace

void MonitorEvaluationRate::update(std::uint64_t identity, std::uint64_t count, double now) {
    if (!initialized_ || identity_ != identity || count < count_ || now < sampled_at_) {
        initialized_ = true;
        identity_ = identity;
        count_ = count;
        sampled_at_ = now;
        fps_ = 0;
    } else if (now - sampled_at_ >= 0.5) {
        fps_ = static_cast<double>(count - count_) / (now - sampled_at_);
        count_ = count;
        sampled_at_ = now;
    }
}

std::string state_text(InstanceState state) {
    switch (state) {
        case InstanceState::connecting:
            return "Connecting";
        case InstanceState::ready:
            return "Ready";
        case InstanceState::failed:
            return "Failed";
        case InstanceState::stopped:
            return "Stopped";
    }
    return {};
}

std::string phase_text(TimerPhase phase) {
    switch (phase) {
        case TimerPhase::not_running:
            return "Not running";
        case TimerPhase::running:
            return "Running";
        case TimerPhase::paused:
            return "Paused";
        case TimerPhase::ended:
            return "Ended";
        case TimerPhase::unspecified:
            return "Unknown";
    }
    return {};
}

std::string latency_text(double milliseconds, bool measured) {
    if (!measured) {
        return "-";
    }
    std::ostringstream stream;
    stream << std::fixed << std::setprecision(2) << milliseconds << " ms";
    return stream.str();
}

std::vector<EvaluationGroup> evaluation_groups(const InstanceDiagnosticsSnapshot& instance) {
    std::vector<EvaluationGroup> result;
    if (!instance.scenario.has_value()) {
        return result;
    }
    const auto& scenario = *instance.scenario;
    if (!scenario.configuration_valid) {
        result.push_back(EvaluationGroup{
            {}, {EvaluationLine{"Scenario / split count mismatch", {}, 0, false}}});
        return result;
    }
    if (!scenario.snapshot.has_value()) {
        result.push_back(
            EvaluationGroup{{}, {EvaluationLine{"Waiting for timer state", {}, 0, false}}});
        return result;
    }
    if (scenario.reset_pending.has_value()) {
        result.push_back(EvaluationGroup{
            {}, {EvaluationLine{"Waiting for Reset confirmation", {}, 0, false}}});
        return result;
    }

    std::vector<EvaluationLine> pending;
    if (scenario.pending_action.has_value()) {
        pending.push_back(EvaluationLine{
            "Pending: " + std::string{to_string(*scenario.pending_action)}, {}, 0, false});
    }

    const auto& snapshot = *scenario.snapshot;
    if (snapshot.phase == TimerPhase::not_running) {
        append_group(scenario.start, "Start", 0, result);
    } else if (snapshot.phase == TimerPhase::ended) {
        append_group(scenario.incomplete, "Incomplete", 0, result);
    } else if (
        snapshot.phase == TimerPhase::running || snapshot.phase == TimerPhase::paused) {
        append_group(scenario.reset, "Reset", 0, result);
        if (snapshot.split_index >= 0 &&
            static_cast<std::size_t>(snapshot.split_index) < scenario.splits.size()) {
            const auto& split = scenario.splits[static_cast<std::size_t>(snapshot.split_index)];
            EvaluationGroup group;
            group.label = "Split " + std::to_string(split.index + 1);
            const auto name = segment_name(instance, split.index);
            if (!name.empty()) {
                group.label += " - " + name;
            }
            append_rules(split.rules, 1, group.lines);
            if (!group.lines.empty()) {
                result.push_back(std::move(group));
            }
        }
    }

    if (!pending.empty()) {
        if (result.empty()) {
            result.push_back(EvaluationGroup{{}, std::move(pending)});
        } else {
            result.front().lines.insert(
                result.front().lines.begin(), pending.begin(), pending.end());
        }
    }
    return result;
}

std::string scenario_overview(const ScenarioDiagnosticsSnapshot& scenario) {
    InstanceDiagnosticsSnapshot instance;
    instance.scenario = scenario;
    const auto groups = evaluation_groups(instance);
    std::string result;
    for (const auto& group : groups) {
        if (!group.label.empty()) {
            if (!result.empty()) result += '\n';
            result += group.label;
        }
        for (const auto& line : group.lines) {
            if (!result.empty()) result += '\n';
            result.append(static_cast<std::size_t>(line.depth) * 2, ' ');
            result += line.label;
            if (!line.detail.empty()) {
                result += " | " + line.detail;
            }
        }
    }
    return result.empty() ? "No condition configured" : result;
}

ScenarioCardModel card_model(const InstanceDiagnosticsSnapshot& instance) {
    ScenarioCardModel data;
    data.index = instance.index;
    data.has_state = true;
    data.state = instance.state;
    data.status = state_text(instance.state);
    data.error = instance.error;
    if (instance.last_action) data.action_status = "Last action: " + std::string{to_string(*instance.last_action)} + " | " + instance.last_action_result;
    data.groups = evaluation_groups(instance);
    if (instance.scenario) {
        const auto& scenario = *instance.scenario;
        data.history = scenario.history;
        if (!scenario.configuration_valid) data.notice = "Scenario / split count mismatch";
        else if (!scenario.snapshot) data.notice = "Waiting for timer state";
        else if (scenario.reset_pending) data.notice = "Waiting for Reset confirmation";
        else if (scenario.pending_action) data.notice = "Pending: " + std::string{to_string(*scenario.pending_action)};
        const auto phase = scenario.snapshot ? scenario.snapshot->phase : TimerPhase::unspecified;
        const bool eligible = scenario.configuration_valid && scenario.snapshot && !scenario.reset_pending;
        const bool running = phase == TimerPhase::running || phase == TimerPhase::paused;
        if (scenario.snapshot) {
            const auto& timer = *scenario.snapshot;
            data.timer_status = phase_text(timer.phase) + " | Split " +
                std::to_string(timer.split_index + 1) + " / " + std::to_string(timer.split_count);
        }
        const auto append = [&](const auto& groups, const char* name, bool current) {
            for (const auto& group : groups)
                if (!group.rules.empty()) data.rule_groups.push_back({name, group.rules, group.name, current});
        };
        append(scenario.start, "Start", eligible && phase == TimerPhase::not_running);
        append(scenario.reset, "Reset", eligible && running);
        append(scenario.incomplete, "Incomplete", eligible && phase == TimerPhase::ended);
        // Keep all configured splits addressable, including after Ended/Reset or Undo.
        for (const auto& split : scenario.splits) {
            if (split.rules.empty()) continue;
            auto label = "Split " + std::to_string(split.index + 1);
            const auto name = segment_name(instance, split.index);
            if (!name.empty()) label += " - " + name;
            const bool current = eligible && running && scenario.snapshot->split_index >= 0 &&
                split.index == static_cast<std::size_t>(scenario.snapshot->split_index);
            data.rule_groups.push_back({label, split.rules, split.path, current});
        }
    }

    if (!data.error.empty()) {
        EvaluationGroup error_group;
        error_group.lines.push_back(EvaluationLine{"Error: " + data.error, {}, 0, false});
        data.groups.insert(data.groups.begin(), std::move(error_group));
    }
    if (instance.scenario.has_value()) {
        const bool measured = instance.scenario->evaluation_count > 0;
        data.average = latency_text(instance.scenario->average_evaluation_ms, measured);
        data.maximum = latency_text(instance.scenario->max_evaluation_ms, measured);
    } else {
        data.average = "-";
        data.maximum = "-";
    }
    return data;
}

const ConditionDiagnosticsNode* find_condition(const ScenarioCardModel& card, std::string_view path) {
    const auto condition = [&](const auto& self, const ConditionDiagnosticsNode& node) -> const ConditionDiagnosticsNode* {
        if (node.path == path) return &node;
        for (const auto& child : node.children)
            if (const auto* found = self(self, child)) return found;
        return nullptr;
    };
    const auto rule = [&](const auto& self, const RuleDiagnosticsNode& node) -> const ConditionDiagnosticsNode* {
        if (const auto* found = condition(condition, node.condition)) return found;
        for (const auto& child : node.sequence_rules)
            if (const auto* found = self(self, child)) return found;
        return nullptr;
    };
    for (const auto& group : card.rule_groups)
        for (const auto& node : group.rules)
            if (const auto* found = rule(rule, node)) return found;
    return nullptr;
}

CompactConditionRow compact_condition_row(const ConditionDiagnosticsNode& node) {
    CompactConditionRow row;
    row.anchor = &node;
    const auto unary = [](std::string_view type) {
        return type == "hold" || type == "nth" || type == "once" || type == "not" ||
               type == "rising_edge" || type == "falling_edge";
    };
    const ConditionDiagnosticsNode* current = &node;
    while (true) {
        if (!row.label.empty()) row.label += " \xC2\xB7 ";
        row.label += current->type;
        if (!row.graph && unary(current->type) && current->type != "not") row.graph = current;
        if (!unary(current->type) || current->children.size() != 1) break;
        current = &current->children.front();
    }
    if (!current->children.empty()) row.branch = current;
    if (!row.graph && !row.branch) row.graph = current;
    if (current->type == "then") {
        const auto count = current->children.size();
        row.label += current->completed ? " | Complete " : " | ";
        const auto step = current->completed ? count : std::min(current->active_step.value_or(0) + 1, count);
        row.label += std::to_string(step) + " / " + std::to_string(count);
    }
    return row;
}

std::vector<CompactConditionChild> compact_condition_children(const CompactConditionRow& row) {
    std::vector<CompactConditionChild> result;
    if (!row.branch) return result;
    const auto& branch = *row.branch;
    if (branch.type == "then") {
        if (!branch.completed) {
            const auto step = branch.active_step.value_or(0);
            if (step < branch.children.size()) result.push_back({&branch.children[step], {}});
        }
    } else {
        for (std::size_t i = 0; i < branch.children.size(); ++i) {
            std::string role;
            if (branch.type == "reset_when") role = i == 0 ? "Condition" : "Reset";
            result.push_back({&branch.children[i], std::move(role)});
        }
    }
    return result;
}

const RuleDiagnosticsNode* compact_sequence_rule(const RuleDiagnosticsNode& rule) {
    if (!rule.active_rule_index || *rule.active_rule_index >= rule.sequence_rules.size()) return nullptr;
    return &rule.sequence_rules[*rule.active_rule_index];
}

std::vector<InspectorRuleRoot> inspector_rule_roots(const ScenarioCardModel& card) {
    std::vector<InspectorRuleRoot> result;
    const auto append = [&](const auto& self, const RuleDiagnosticsNode& rule,
                            const std::string& label, bool current) -> void {
        const auto name = label + " / Rule " + std::to_string(rule.index + 1);
        if (!rule.sequence_rules.empty()) {
            for (std::size_t i = 0; i < rule.sequence_rules.size(); ++i)
                self(self, rule.sequence_rules[i], name,
                     current && rule.active_rule_index == i);
        } else if (!rule.condition.type.empty() && rule.condition.type != "none") {
            result.push_back({&rule.condition, name, current});
        }
    };
    for (const auto& group : card.rule_groups)
        for (const auto& rule : group.rules) append(append, rule, group.label, group.current);
    return result;
}

bool condition_is_current(const ScenarioCardModel& card, std::string_view path) {
    const auto visit = [&](const auto& self, const ConditionDiagnosticsNode& node,
                           bool current) -> std::optional<bool> {
        if (node.path == path) return current;
        for (std::size_t i = 0; i < node.children.size(); ++i) {
            const bool active = current && (node.type != "then" ||
                (!node.completed && node.active_step == i));
            if (const auto found = self(self, node.children[i], active)) return found;
        }
        return {};
    };
    for (const auto& root : inspector_rule_roots(card))
        if (const auto found = visit(visit, *root.condition, root.current)) return *found;
    return false;
}

}  // namespace divergencesplitter::ui
