#include "divergencesplitter/rule/rule.hpp"

#include <stdexcept>

namespace divergencesplitter {

std::string_view to_string(ActionOperation operation) noexcept {
    switch (operation) {
        case ActionOperation::start:
            return "start";
        case ActionOperation::split:
            return "split";
        case ActionOperation::skip:
            return "skip";
        case ActionOperation::undo:
            return "undo";
        case ActionOperation::reset:
            return "reset";
        case ActionOperation::pause:
            return "pause";
        case ActionOperation::resume:
            return "resume";
    }
    return "unknown";
}

std::optional<ActionOperation> parse_action(std::string_view value) noexcept {
    if (value == "start") {
        return ActionOperation::start;
    }
    if (value == "split") {
        return ActionOperation::split;
    }
    if (value == "skip") {
        return ActionOperation::skip;
    }
    if (value == "undo") {
        return ActionOperation::undo;
    }
    if (value == "reset") {
        return ActionOperation::reset;
    }
    if (value == "pause") {
        return ActionOperation::pause;
    }
    if (value == "resume") {
        return ActionOperation::resume;
    }
    return std::nullopt;
}

Rule::Rule(ConditionPtr condition, Action action)
    : condition_(std::move(condition)), action_(action) {
    if (!condition_) {
        throw std::invalid_argument("condition must not be null");
    }
}

std::optional<Action> Rule::evaluate(FrameContext& context) {
    const auto result = condition_->evaluate(context);
    if (!result.has_value()) {
        throw std::logic_error("root condition did not return a boolean result");
    }
    if (*result) {
        return action_;
    }
    return std::nullopt;
}

void Rule::reset() {
    condition_->reset();
}

RuleSequence::RuleSequence(std::vector<std::shared_ptr<Rule>> rules)
    : rules_(std::move(rules)) {
    if (rules_.empty()) {
        throw std::invalid_argument("RuleSequence requires at least one rule");
    }
    for (const auto& rule : rules_) {
        if (!rule) {
            throw std::invalid_argument("RuleSequence accepts rules only");
        }
    }
}

std::optional<Action> RuleSequence::evaluate(FrameContext& context) {
    if (index_ >= rules_.size()) {
        return std::nullopt;
    }
    auto action = rules_[index_]->evaluate(context);
    if (action.has_value()) {
        ++index_;
    }
    return action;
}

void RuleSequence::reset() {
    index_ = 0;
    for (const auto& rule : rules_) {
        rule->reset();
    }
}

const Condition* RuleSequence::active_condition() const noexcept {
    if (index_ >= rules_.size()) {
        return nullptr;
    }
    return rules_[index_]->condition().get();
}

std::optional<std::size_t> RuleSequence::active_rule_index() const noexcept {
    if (index_ >= rules_.size()) {
        return std::nullopt;
    }
    return index_;
}

}  // namespace divergencesplitter
