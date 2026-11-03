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
    // A decision has no confirmation deadline until its RPC succeeds.
    void action_accepted(const Action& action, MonotonicTime accepted_at);
    [[nodiscard]] std::optional<Action> request_reset();
    [[nodiscard]] bool action_pending(const Action& action) const;
    [[nodiscard]] std::optional<MonotonicTime> state_wait_deadline() const;
    // The instance queries authoritative state before expiring a wait.
    void state_wait_timed_out(MonotonicTime now);
    // Reconcile a rejected Reset from a successful authoritative Query. A later
    // frame may decide a fresh action; no old normal/Reset wait survives.
    void settle_rejected_reset(const LiveSplitUpdate& update);

    [[nodiscard]] std::optional<LiveSplitSnapshot> current_snapshot() const;
    [[nodiscard]] ScenarioDiagnosticsSnapshot diagnostics() const;

private:
    [[nodiscard]] std::optional<Action> evaluate_rules(
        const std::vector<ScenarioRulePtr>& rules,
        FrameContext& context,
        const LiveSplitSnapshot& snapshot
    );
    void start_action(const Action& action);
    void clear_pending_action();
    void clear_reset_pending();
    void clear_all_pending();
    void reset_pending_action(const LiveSplitSnapshot& snapshot);
    void apply_transition_resets(
        const LiveSplitSnapshot& current,
        const LiveSplitSnapshot& snapshot
    );
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
    std::optional<MonotonicTime> state_wait_started_at_;
    std::optional<Action> reset_pending_;
    std::optional<MonotonicTime> reset_state_wait_started_at_;
    std::uint64_t evaluation_count_{};
    double last_evaluation_ms_{};
    std::uint64_t rule_errors_{};
};

}  // namespace divergencesplitter
