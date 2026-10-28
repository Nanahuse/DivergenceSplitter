#pragma once

#include <cstdint>
#include <mutex>
#include <optional>
#include <vector>

#include "divergencesplitter/frame.hpp"
#include "divergencesplitter/runtime/diagnostics.hpp"
#include "divergencesplitter/runtime/models.hpp"
#include "divergencesplitter/scenario/scenario.hpp"

namespace divergencesplitter {

class ScenarioRuntime {
public:
    explicit ScenarioRuntime(Scenario scenario);

    void apply_update(const LiveSplitUpdate& update);
    [[nodiscard]] std::optional<Action> evaluate(FrameContext context);
    void action_not_dispatched(const Action& action);

    [[nodiscard]] std::optional<LiveSplitSnapshot> current_snapshot() const;
    [[nodiscard]] ScenarioDiagnosticsSnapshot diagnostics() const;

private:
    [[nodiscard]] std::optional<Action> evaluate_rules(
        const std::vector<ScenarioRulePtr>& rules,
        FrameContext& context,
        const LiveSplitSnapshot& snapshot
    );
    void start_action(const Action& action, const FrameContext& context);
    void clear_pending_action();
    void reset_pending_action(const LiveSplitSnapshot& snapshot);
    void apply_transition_resets(
        const LiveSplitSnapshot& current,
        const LiveSplitSnapshot& snapshot
    );
    void apply_resync(const LiveSplitSnapshot& snapshot, const LiveSplitSnapshot& current);
    void establish_baseline(const LiveSplitSnapshot& snapshot);
    [[nodiscard]] bool validate_split_count(const LiveSplitSnapshot& snapshot);
    void reset_all_rules();
    void reset_rule_group(const std::vector<ScenarioRulePtr>& rules);
    void reset_split_group(std::size_t split_index);
    [[nodiscard]] static std::optional<std::size_t> evaluation_index(
        const LiveSplitSnapshot& snapshot
    );

    Scenario scenario_;
    std::vector<ScenarioRulePtr> start_rules_;
    std::vector<ScenarioRulePtr> reset_rules_;
    std::vector<ScenarioRulePtr> incomplete_rules_;

    mutable std::mutex mutex_;
    std::optional<LiveSplitSnapshot> snapshot_;
    bool configuration_valid_{true};
    std::optional<Action> pending_action_;
    std::optional<MonotonicTime> action_started_at_;
    std::uint64_t evaluation_count_{};
    double last_evaluation_ms_{};
    std::uint64_t rule_errors_{};
};

}  // namespace divergencesplitter
