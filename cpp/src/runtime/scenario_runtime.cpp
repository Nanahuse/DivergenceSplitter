#include "divergencesplitter/runtime/scenario_runtime.hpp"

#include <chrono>
#include <stdexcept>
#include <string>

#include "divergencesplitter/condition/conditions.hpp"

namespace divergencesplitter {
namespace {

constexpr auto kSplitTransitionTimeout = std::chrono::seconds{1};

ConditionDiagnosticsNode make_condition_node(const Condition* condition) {
    ConditionDiagnosticsNode node;
    if (condition == nullptr) {
        node.type = "none";
        node.status = "not_evaluated";
        return node;
    }
    node.type = std::string{condition->type_name()};
    node.status = std::string{to_string(condition->status())};
    node.description = condition->describe();
    if (const auto* detected = dynamic_cast<const DetectedCondition*>(condition)) {
        node.detector_type = std::string{detected->detector()->type_name()};
        node.minimum_score = detected->minimum_score();
    }
    node.latest_score = condition->latest_score();
    node.max_score = condition->max_score();
    for (const auto* child : condition->children()) {
        node.children.push_back(make_condition_node(child));
    }
    return node;
}

RuleDiagnosticsNode make_rule_node(const std::shared_ptr<ScenarioRule>& rule, std::size_t index) {
    RuleDiagnosticsNode node;
    node.index = index;
    if (const auto* sequence = dynamic_cast<const RuleSequence*>(rule.get())) {
        node.type = std::string{sequence->type_name()};
        node.active_rule_index = sequence->active_rule_index();
        for (std::size_t rule_index = 0; rule_index < sequence->rules().size(); ++rule_index) {
            node.sequence_rules.push_back(make_rule_node(
                std::static_pointer_cast<ScenarioRule>(sequence->rules()[rule_index]),
                rule_index
            ));
        }
        return node;
    }
    if (const auto* single = dynamic_cast<const Rule*>(rule.get())) {
        node.type = std::string{single->type_name()};
        node.action = single->action().operation;
        node.condition = make_condition_node(single->condition().get());
        return node;
    }
    node.type = std::string{rule->type_name()};
    node.condition = make_condition_node(rule->active_condition());
    return node;
}

std::vector<RuleDiagnosticsNode> make_rule_nodes(
    const std::vector<ScenarioRulePtr>& rules
) {
    std::vector<RuleDiagnosticsNode> nodes;
    nodes.reserve(rules.size());
    for (std::size_t index = 0; index < rules.size(); ++index) {
        nodes.push_back(make_rule_node(rules[index], index));
    }
    return nodes;
}

}  // namespace

ScenarioRuntime::ScenarioRuntime(Scenario scenario) : scenario_(std::move(scenario)) {
    if (!scenario_.start_condition) {
        throw std::invalid_argument("scenario start_condition is required");
    }
    start_rules_.push_back(std::make_shared<Rule>(
        scenario_.start_condition,
        Action{ActionOperation::start}
    ));
    if (scenario_.reset_condition) {
        reset_rules_.push_back(std::make_shared<Rule>(
            scenario_.reset_condition,
            Action{ActionOperation::reset}
        ));
    }
    if (scenario_.incomplete_condition) {
        incomplete_rules_.push_back(std::make_shared<Rule>(
            scenario_.incomplete_condition,
            Action{ActionOperation::undo}
        ));
    }
}

void ScenarioRuntime::apply_update(const LiveSplitUpdate& update) {
    std::scoped_lock lock{mutex_};
    const auto& snapshot = update.snapshot;
    if (!snapshot_.has_value()) {
        if (update.kind != UpdateKind::initial && update.kind != UpdateKind::resync) {
            return;
        }
        establish_baseline(snapshot);
        return;
    }

    const auto current = *snapshot_;
    if (snapshot.session_id != current.session_id) {
        if (update.kind != UpdateKind::resync) {
            return;
        }
        establish_baseline(snapshot);
        return;
    }

    if (update.kind == UpdateKind::resync) {
        if (snapshot.state_revision < current.state_revision) {
            return;
        }
        apply_resync(snapshot, current);
        return;
    }

    if (update.kind == UpdateKind::initial) {
        return;
    }

    if (snapshot.state_revision < current.state_revision) {
        return;
    }

    const bool run_changed =
        snapshot.run_revision != current.run_revision ||
        snapshot.split_count != current.split_count;
    if (snapshot.state_revision == current.state_revision && !run_changed) {
        return;
    }

    snapshot_ = snapshot;
    configuration_valid_ = validate_split_count(snapshot);
    if (update.kind == UpdateKind::transition || run_changed) {
        apply_transition_resets(current, snapshot);
        clear_pending_action();
    }
}

std::optional<Action> ScenarioRuntime::evaluate(FrameContext context) {
    const auto wall_started = std::chrono::steady_clock::now();
    std::scoped_lock lock{mutex_};
    ++evaluation_count_;
    const auto finish = [&]() {
        const auto wall_completed = std::chrono::steady_clock::now();
        last_evaluation_ms_ =
            std::chrono::duration<double, std::milli>(wall_completed - wall_started).count();
    };

    if (!snapshot_.has_value() || !configuration_valid_) {
        finish();
        return std::nullopt;
    }
    const auto snapshot = *snapshot_;

    if (pending_action_.has_value() &&
        (pending_action_->operation == ActionOperation::split ||
         pending_action_->operation == ActionOperation::skip)) {
        auto reset_action = evaluate_rules(reset_rules_, context, snapshot);
        if (reset_action.has_value()) {
            start_action(*reset_action, context);
            finish();
            return reset_action;
        }
    }

    if (pending_action_.has_value()) {
        if (!action_started_at_.has_value()) {
            finish();
            return std::nullopt;
        }
        const auto elapsed = context.now() - *action_started_at_;
        if (elapsed < std::chrono::duration_cast<std::chrono::nanoseconds>(kSplitTransitionTimeout)) {
            finish();
            return std::nullopt;
        }
        reset_pending_action(snapshot);
        clear_pending_action();
        finish();
        return std::nullopt;
    }

    std::optional<Action> action;
    if (snapshot.phase == TimerPhase::not_running) {
        action = evaluate_rules(start_rules_, context, snapshot);
    } else if (snapshot.phase == TimerPhase::ended) {
        action = evaluate_rules(incomplete_rules_, context, snapshot);
    } else if (snapshot.phase == TimerPhase::running || snapshot.phase == TimerPhase::paused) {
        auto reset_action = evaluate_rules(reset_rules_, context, snapshot);
        if (reset_action.has_value()) {
            start_action(*reset_action, context);
            finish();
            return reset_action;
        }
        const auto split_index = evaluation_index(snapshot);
        if (!split_index.has_value() || *split_index >= scenario_.splits.size()) {
            finish();
            return std::nullopt;
        }
        const auto& rules = scenario_.splits[*split_index];
        if (!rules.has_value()) {
            finish();
            return std::nullopt;
        }
        action = evaluate_rules(*rules, context, snapshot);
    }

    if (action.has_value()) {
        start_action(*action, context);
    }
    finish();
    return action;
}

void ScenarioRuntime::action_not_dispatched(const Action& action) {
    std::scoped_lock lock{mutex_};
    if (!pending_action_.has_value()) {
        return;
    }
    if (snapshot_.has_value()) {
        reset_pending_action(*snapshot_);
    }
    clear_pending_action();
    (void)action;
}

std::optional<LiveSplitSnapshot> ScenarioRuntime::current_snapshot() const {
    std::scoped_lock lock{mutex_};
    return snapshot_;
}

ScenarioDiagnosticsSnapshot ScenarioRuntime::diagnostics() const {
    std::scoped_lock lock{mutex_};
    ScenarioDiagnosticsSnapshot result;
    result.snapshot = snapshot_;
    result.configuration_valid = configuration_valid_;
    if (pending_action_.has_value()) {
        result.pending_action = pending_action_->operation;
    }
    result.start.push_back(RuleGroupDiagnostics{"start", make_rule_nodes(start_rules_)});
    result.reset.push_back(RuleGroupDiagnostics{"reset", make_rule_nodes(reset_rules_)});
    result.incomplete.push_back(
        RuleGroupDiagnostics{"incomplete", make_rule_nodes(incomplete_rules_)}
    );
    for (std::size_t index = 0; index < scenario_.splits.size(); ++index) {
        SplitDiagnosticsNode split;
        split.index = index;
        split.configured = scenario_.splits[index].has_value();
        if (split.configured) {
            split.rules = make_rule_nodes(*scenario_.splits[index]);
        }
        result.splits.push_back(std::move(split));
    }
    result.evaluation_count = evaluation_count_;
    result.last_evaluation_ms = last_evaluation_ms_;
    result.rule_errors = rule_errors_;
    return result;
}

std::optional<Action> ScenarioRuntime::evaluate_rules(
    const std::vector<ScenarioRulePtr>& rules,
    FrameContext& context,
    const LiveSplitSnapshot& snapshot
) {
    (void)snapshot;
    for (const auto& rule : rules) {
        try {
            auto action = rule->evaluate(context);
            if (action.has_value()) {
                return action;
            }
        } catch (const std::exception&) {
            ++rule_errors_;
            continue;
        } catch (...) {
            ++rule_errors_;
            continue;
        }
    }
    return std::nullopt;
}

void ScenarioRuntime::start_action(const Action& action, const FrameContext& context) {
    pending_action_ = action;
    action_started_at_ = context.now();
}

void ScenarioRuntime::clear_pending_action() {
    pending_action_.reset();
    action_started_at_.reset();
}

void ScenarioRuntime::reset_pending_action(const LiveSplitSnapshot& snapshot) {
    if (!pending_action_.has_value()) {
        return;
    }
    switch (pending_action_->operation) {
        case ActionOperation::start:
            reset_rule_group(start_rules_);
            break;
        case ActionOperation::undo:
            reset_rule_group(incomplete_rules_);
            break;
        case ActionOperation::reset:
            reset_rule_group(reset_rules_);
            break;
        default: {
            const auto split_index = evaluation_index(snapshot);
            if (split_index.has_value()) {
                reset_split_group(*split_index);
            }
            break;
        }
    }
}

void ScenarioRuntime::apply_transition_resets(
    const LiveSplitSnapshot& current,
    const LiveSplitSnapshot& snapshot
) {
    if (snapshot.phase == TimerPhase::not_running ||
        snapshot.split_count != current.split_count) {
        reset_all_rules();
        return;
    }
    if (current.phase == TimerPhase::ended &&
        (snapshot.phase == TimerPhase::running || snapshot.phase == TimerPhase::paused)) {
        reset_rule_group(incomplete_rules_);
        reset_rule_group(reset_rules_);
    } else if (snapshot.phase == TimerPhase::ended) {
        reset_rule_group(incomplete_rules_);
        return;
    }
    const auto destination = evaluation_index(snapshot);
    if (destination.has_value() &&
        (destination != evaluation_index(current) || snapshot.phase == current.phase)) {
        reset_split_group(*destination);
    }
}

void ScenarioRuntime::apply_resync(
    const LiveSplitSnapshot& snapshot,
    const LiveSplitSnapshot& current
) {
    if (snapshot.state_revision < current.state_revision) {
        return;
    }
    const bool revision_advanced = snapshot.state_revision > current.state_revision;
    const bool run_changed =
        snapshot.run_revision != current.run_revision ||
        snapshot.split_count != current.split_count;
    snapshot_ = snapshot;
    configuration_valid_ = validate_split_count(snapshot);
    clear_pending_action();
    if (revision_advanced || run_changed) {
        reset_all_rules();
    }
}

void ScenarioRuntime::establish_baseline(const LiveSplitSnapshot& snapshot) {
    snapshot_ = snapshot;
    configuration_valid_ = validate_split_count(snapshot);
    clear_pending_action();
    reset_all_rules();
}

bool ScenarioRuntime::validate_split_count(const LiveSplitSnapshot& snapshot) {
    if (snapshot.phase == TimerPhase::not_running && snapshot.split_count == 0) {
        return true;
    }
    return static_cast<std::int32_t>(scenario_.splits.size()) <= snapshot.split_count;
}

void ScenarioRuntime::reset_all_rules() {
    reset_rule_group(start_rules_);
    reset_rule_group(reset_rules_);
    reset_rule_group(incomplete_rules_);
    for (std::size_t index = 0; index < scenario_.splits.size(); ++index) {
        reset_split_group(index);
    }
}

void ScenarioRuntime::reset_rule_group(const std::vector<ScenarioRulePtr>& rules) {
    for (const auto& rule : rules) {
        try {
            rule->reset();
        } catch (const std::exception&) {
            ++rule_errors_;
        } catch (...) {
            ++rule_errors_;
        }
    }
}

void ScenarioRuntime::reset_split_group(std::size_t split_index) {
    if (split_index >= scenario_.splits.size()) {
        return;
    }
    const auto& rules = scenario_.splits[split_index];
    if (!rules.has_value()) {
        return;
    }
    reset_rule_group(*rules);
}

std::optional<std::size_t> ScenarioRuntime::evaluation_index(
    const LiveSplitSnapshot& snapshot
) {
    if (snapshot.phase == TimerPhase::running || snapshot.phase == TimerPhase::paused) {
        if (snapshot.split_index < 0) {
            return std::nullopt;
        }
        return static_cast<std::size_t>(snapshot.split_index);
    }
    return std::nullopt;
}

}  // namespace divergencesplitter
