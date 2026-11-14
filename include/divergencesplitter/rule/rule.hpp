#pragma once

#include <memory>
#include <optional>
#include <string_view>
#include <vector>

#include "divergencesplitter/condition/condition.hpp"

namespace divergencesplitter {

enum class ActionOperation {
    start,
    split,
    skip,
    undo,
    reset,
    pause,
    resume,
};

[[nodiscard]] std::string_view to_string(ActionOperation operation) noexcept;
[[nodiscard]] std::optional<ActionOperation> parse_action(std::string_view value) noexcept;

struct Action {
    ActionOperation operation{};

    friend bool operator==(const Action&, const Action&) = default;
};

class ScenarioRule {
public:
    virtual ~ScenarioRule() = default;
    [[nodiscard]] virtual std::optional<Action> evaluate(FrameContext& context) = 0;
    virtual void reset() = 0;
    [[nodiscard]] virtual std::string_view type_name() const noexcept = 0;
    [[nodiscard]] virtual const Condition* active_condition() const noexcept = 0;
    [[nodiscard]] virtual std::optional<std::size_t> active_rule_index() const noexcept {
        return std::nullopt;
    }
};

using ScenarioRulePtr = std::shared_ptr<ScenarioRule>;

class Rule final : public ScenarioRule {
public:
    Rule(ConditionPtr condition, Action action);

    [[nodiscard]] std::optional<Action> evaluate(FrameContext& context) override;
    void reset() override;

    [[nodiscard]] std::string_view type_name() const noexcept override { return "rule"; }
    [[nodiscard]] const Condition* active_condition() const noexcept override { return condition_.get(); }
    [[nodiscard]] const ConditionPtr& condition() const noexcept { return condition_; }
    [[nodiscard]] const Action& action() const noexcept { return action_; }

private:
    ConditionPtr condition_;
    Action action_;
};

class RuleSequence final : public ScenarioRule {
public:
    explicit RuleSequence(std::vector<std::shared_ptr<Rule>> rules);

    [[nodiscard]] std::optional<Action> evaluate(FrameContext& context) override;
    void reset() override;

    [[nodiscard]] std::string_view type_name() const noexcept override { return "sequence"; }
    [[nodiscard]] const Condition* active_condition() const noexcept override;
    [[nodiscard]] std::optional<std::size_t> active_rule_index() const noexcept override;
    [[nodiscard]] const std::vector<std::shared_ptr<Rule>>& rules() const noexcept { return rules_; }

private:
    std::vector<std::shared_ptr<Rule>> rules_;
    std::size_t index_{};
};

}  // namespace divergencesplitter
