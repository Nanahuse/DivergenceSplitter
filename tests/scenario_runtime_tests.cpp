#include <gtest/gtest.h>

#include <chrono>
#include <memory>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
#include "divergencesplitter/rule/rule.hpp"
#include "divergencesplitter/runtime/scenario_runtime.hpp"
#include "test_support.hpp"

using namespace divergencesplitter;

namespace {

ConditionPtr visible() {
    return std::make_shared<DetectedCondition>(
        std::make_shared<MeanBrightnessDetector>(),
        0.5
    );
}

ConditionPtr invisible() {
    return std::make_shared<NotCondition>(visible());
}

ScenarioRulePtr rule(ConditionPtr condition, ActionOperation operation) {
    return std::make_shared<Rule>(std::move(condition), Action{operation});
}

LiveSplitSnapshot snapshot(
    TimerPhase phase,
    std::int32_t split_index,
    std::int32_t split_count,
    std::uint32_t session = 1,
    std::uint64_t state_revision = 1,
    std::uint64_t run_revision = 1
) {
    return LiveSplitSnapshot{session, state_revision, run_revision, phase, split_index, split_count};
}

LiveSplitUpdate update(
    UpdateKind kind,
    TimerPhase phase,
    std::int32_t split_index,
    std::int32_t split_count,
    std::uint32_t session = 1,
    std::uint64_t state_revision = 1,
    std::uint64_t run_revision = 1
) {
    LiveSplitUpdate value;
    value.kind = kind;
    value.snapshot = snapshot(
        phase,
        split_index,
        split_count,
        session,
        state_revision,
        run_revision
    );
    return value;
}

FrameContext white_frame(test::ManualTimeProvider& clock) {
    return test::make_context(test::solid(2, 2, 255), clock);
}

}  // namespace

TEST(ScenarioRuntime, StartActionFromNotRunning) {
    Scenario scenario;
    scenario.start_condition = visible();
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::not_running, -1, 2));

    test::ManualTimeProvider clock;
    auto action = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(action.has_value());
    EXPECT_EQ(action->operation, ActionOperation::start);
}

TEST(ScenarioRuntime, PendingActionPreventsDuplicatesUntilTimeout) {
    Scenario scenario;
    scenario.start_condition = visible();
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::not_running, -1, 2));

    test::ManualTimeProvider clock;
    const auto action = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(action.has_value());
    runtime.action_accepted(*action, clock.now());
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());

    clock.advance(std::chrono::milliseconds{1100});
    runtime.state_wait_timed_out(clock.now());
    EXPECT_TRUE(runtime.evaluate(white_frame(clock)).has_value());
}

TEST(ScenarioRuntime, ResetHasPriorityOverSplit) {
    Scenario scenario;
    scenario.start_condition = invisible();
    scenario.reset_condition = visible();
    scenario.splits.push_back(
        std::vector<ScenarioRulePtr>{rule(visible(), ActionOperation::split)}
    );
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2));

    test::ManualTimeProvider clock;
    auto action = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(action.has_value());
    EXPECT_EQ(action->operation, ActionOperation::reset);
}

TEST(ScenarioRuntime, PendingSplitIsInterruptedByReset) {
    Scenario scenario;
    scenario.start_condition = invisible();
    scenario.reset_condition = std::make_shared<ElapsedCondition>(std::chrono::seconds{1});
    scenario.splits.push_back(
        std::vector<ScenarioRulePtr>{rule(visible(), ActionOperation::split)}
    );
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2));

    test::ManualTimeProvider clock;
    auto first = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(first.has_value());
    EXPECT_EQ(first->operation, ActionOperation::split);

    clock.advance(std::chrono::milliseconds{1100});
    auto second = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(second.has_value());
    EXPECT_EQ(second->operation, ActionOperation::reset);
}

TEST(ScenarioRuntime, EndedUsesIncompleteCondition) {
    Scenario scenario;
    scenario.start_condition = invisible();
    scenario.incomplete_condition = visible();
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::ended, 2, 2));

    test::ManualTimeProvider clock;
    auto action = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(action.has_value());
    EXPECT_EQ(action->operation, ActionOperation::undo);
}

TEST(ScenarioRuntime, SplitCountMismatchDisablesEvaluation) {
    Scenario scenario;
    scenario.start_condition = visible();
    scenario.splits.push_back(
        std::vector<ScenarioRulePtr>{rule(visible(), ActionOperation::split)}
    );
    scenario.splits.push_back(std::nullopt);
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 1));

    test::ManualTimeProvider clock;
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());
    EXPECT_FALSE(runtime.diagnostics().configuration_valid);
}

TEST(ScenarioRuntime, StaleRevisionIsIgnored) {
    Scenario scenario;
    scenario.start_condition = visible();
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2, 1, 5));
    runtime.apply_update(update(UpdateKind::periodic, TimerPhase::ended, 2, 2, 1, 3));
    ASSERT_TRUE(runtime.current_snapshot().has_value());
    EXPECT_EQ(runtime.current_snapshot()->phase, TimerPhase::running);
}

TEST(ScenarioRuntime, SessionChangeRequiresResync) {
    Scenario scenario;
    scenario.start_condition = visible();
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2, 1, 1));
    runtime.apply_update(update(UpdateKind::transition, TimerPhase::not_running, -1, 2, 2, 2));
    EXPECT_EQ(runtime.current_snapshot()->phase, TimerPhase::running);

    runtime.apply_update(update(UpdateKind::resync, TimerPhase::not_running, -1, 2, 2, 2));
    EXPECT_EQ(runtime.current_snapshot()->phase, TimerPhase::not_running);
}

TEST(ScenarioRuntime, ActionNotDispatchedAllowsRetry) {
    Scenario scenario;
    scenario.start_condition = visible();
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::not_running, -1, 2));

    test::ManualTimeProvider clock;
    auto first = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(first.has_value());
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());
    runtime.action_not_dispatched(*first);
    EXPECT_TRUE(runtime.evaluate(white_frame(clock)).has_value());
}

TEST(ScenarioRuntime, DiagnosticsExposeConditionTree) {
    Scenario scenario;
    scenario.start_condition = std::make_shared<AllCondition>(
        std::vector<ConditionPtr>{visible(), std::make_shared<NotCondition>(invisible())}
    );
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::not_running, -1, 2));

    test::ManualTimeProvider clock;
    (void)runtime.evaluate(white_frame(clock));
    const auto diagnostics = runtime.diagnostics();
    ASSERT_FALSE(diagnostics.start.empty());
    ASSERT_FALSE(diagnostics.start.front().rules.empty());
    const auto& condition = diagnostics.start.front().rules.front().condition;
    EXPECT_EQ(condition.type, "all");
    EXPECT_EQ(condition.path, "start.r0.cond");
    ASSERT_EQ(condition.children.size(), 2U);
    EXPECT_EQ(condition.children[0].type, "detected");
    EXPECT_EQ(condition.children[0].status, "true");
    EXPECT_EQ(condition.children[0].path, "start.r0.cond.c0");
    EXPECT_EQ(condition.children[1].path, "start.r0.cond.c1");
}

TEST(ScenarioRuntime, TransitionToNewSplitResetsRules) {
    Scenario scenario;
    scenario.start_condition = invisible();
    scenario.splits.push_back(
        std::vector<ScenarioRulePtr>{rule(std::make_shared<OnceCondition>(visible()), ActionOperation::split)}
    );
    scenario.splits.push_back(std::nullopt);
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2));

    test::ManualTimeProvider clock;
    auto first = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(first.has_value());
    EXPECT_EQ(first->operation, ActionOperation::split);

    runtime.apply_update(update(UpdateKind::transition, TimerPhase::running, 1, 2, 1, 2));
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());

    runtime.apply_update(update(UpdateKind::transition, TimerPhase::running, 0, 2, 1, 3));
    auto again = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(again.has_value());
    EXPECT_EQ(again->operation, ActionOperation::split);
}

TEST(ScenarioRuntime, ConfirmationTimeoutStartsAfterRpcSuccess) {
    Scenario scenario;
    scenario.start_condition = std::make_shared<OnceCondition>(visible());
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::not_running, -1, 2));
    test::ManualTimeProvider clock;
    const auto action = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(action.has_value());
    EXPECT_FALSE(runtime.state_wait_deadline().has_value());

    clock.advance(std::chrono::seconds{5});
    runtime.state_wait_timed_out(clock.now());
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());
    runtime.action_accepted(*action, clock.now());
    ASSERT_TRUE(runtime.state_wait_deadline().has_value());
    EXPECT_EQ(*runtime.state_wait_deadline(), clock.now() + std::chrono::seconds{1});

    clock.advance(std::chrono::milliseconds{999});
    runtime.state_wait_timed_out(clock.now());
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());
    clock.advance(std::chrono::milliseconds{1});
    runtime.state_wait_timed_out(clock.now());
    EXPECT_FALSE(runtime.state_wait_deadline().has_value());
    EXPECT_TRUE(runtime.evaluate(white_frame(clock)).has_value());
}

TEST(ScenarioRuntime, PauseResumeAndUnchangedResyncDoNotReleaseSplitWait) {
    Scenario scenario;
    scenario.start_condition = invisible();
    scenario.splits.push_back(std::vector<ScenarioRulePtr>{rule(visible(), ActionOperation::split)});
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2));
    test::ManualTimeProvider clock;
    const auto action = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(action.has_value());
    runtime.action_accepted(*action, clock.now());

    runtime.apply_update(update(UpdateKind::transition, TimerPhase::paused, 0, 2, 1, 2));
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());
    runtime.apply_update(update(UpdateKind::transition, TimerPhase::running, 0, 2, 1, 3));
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());
    runtime.apply_update(update(UpdateKind::resync, TimerPhase::running, 0, 2, 1, 4));
    EXPECT_TRUE(runtime.action_pending(*action));
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());

    runtime.apply_update(update(UpdateKind::transition, TimerPhase::running, 1, 2, 1, 5));
    EXPECT_FALSE(runtime.action_pending(*action));
    EXPECT_FALSE(runtime.state_wait_deadline().has_value());
}

TEST(ScenarioRuntime, CancelledResetPreservesAcceptedSplitWait) {
    Scenario scenario;
    scenario.start_condition = invisible();
    scenario.splits.push_back(std::vector<ScenarioRulePtr>{rule(visible(), ActionOperation::split)});
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2));
    test::ManualTimeProvider clock;
    const auto split = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(split.has_value());
    runtime.action_accepted(*split, clock.now());
    const auto deadline = runtime.state_wait_deadline();

    const auto reset = runtime.request_reset();
    ASSERT_TRUE(reset.has_value());
    EXPECT_TRUE(runtime.action_pending(*split));
    runtime.action_not_dispatched(*reset);
    EXPECT_FALSE(runtime.action_pending(*reset));
    EXPECT_TRUE(runtime.action_pending(*split));
    EXPECT_EQ(runtime.state_wait_deadline(), deadline);
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());
}

TEST(ScenarioRuntime, AcceptedResetAbsorbsSplitButLateSplitDoesNotReleaseResetWait) {
    Scenario scenario;
    scenario.start_condition = invisible();
    scenario.splits.push_back(std::vector<ScenarioRulePtr>{rule(visible(), ActionOperation::split)});
    scenario.splits.push_back(std::vector<ScenarioRulePtr>{rule(visible(), ActionOperation::split)});
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2));
    test::ManualTimeProvider clock;
    const auto split = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(split.has_value());
    runtime.action_accepted(*split, clock.now());
    const auto reset = runtime.request_reset();
    ASSERT_TRUE(reset.has_value());
    clock.advance(std::chrono::milliseconds{500});
    runtime.action_accepted(*reset, clock.now());
    EXPECT_FALSE(runtime.action_pending(*split));
    EXPECT_EQ(runtime.state_wait_deadline(), clock.now() + std::chrono::seconds{1});

    runtime.apply_update(update(UpdateKind::transition, TimerPhase::running, 1, 2, 1, 2));
    EXPECT_TRUE(runtime.action_pending(*reset));
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());
    EXPECT_FALSE(runtime.request_reset().has_value());
    runtime.apply_update(update(UpdateKind::transition, TimerPhase::not_running, -1, 2, 1, 3));
    EXPECT_FALSE(runtime.action_pending(*reset));
    EXPECT_FALSE(runtime.state_wait_deadline().has_value());
}

TEST(ScenarioRuntime, ResetTimeoutRearmsResetRulesWithoutAFrame) {
    Scenario scenario;
    scenario.start_condition = invisible();
    scenario.reset_condition = std::make_shared<OnceCondition>(visible());
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2));
    test::ManualTimeProvider clock;
    const auto reset = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(reset.has_value());
    runtime.action_accepted(*reset, clock.now());
    clock.advance(std::chrono::seconds{1});
    runtime.state_wait_timed_out(clock.now());
    EXPECT_FALSE(runtime.action_pending(*reset));
    EXPECT_TRUE(runtime.evaluate(white_frame(clock)).has_value());
}

TEST(ScenarioRuntime, PauseResumePreservesRuleSequenceProgress) {
    Scenario scenario;
    scenario.start_condition = invisible();
    scenario.splits.push_back(std::vector<ScenarioRulePtr>{std::make_shared<RuleSequence>(
        std::vector<std::shared_ptr<Rule>>{
            std::make_shared<Rule>(visible(), Action{ActionOperation::pause}),
            std::make_shared<Rule>(visible(), Action{ActionOperation::resume}),
            std::make_shared<Rule>(visible(), Action{ActionOperation::split}),
        }
    )});
    ScenarioRuntime runtime{scenario};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2));
    test::ManualTimeProvider clock;
    auto action = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(action.has_value());
    EXPECT_EQ(action->operation, ActionOperation::pause);
    runtime.action_accepted(*action, clock.now());
    runtime.apply_update(update(UpdateKind::transition, TimerPhase::paused, 0, 2, 1, 2));
    action = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(action.has_value());
    EXPECT_EQ(action->operation, ActionOperation::resume);
    runtime.action_accepted(*action, clock.now());
    runtime.apply_update(update(UpdateKind::resync, TimerPhase::paused, 0, 2, 1, 3));
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());
    runtime.apply_update(update(UpdateKind::transition, TimerPhase::running, 0, 2, 1, 4));
    action = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(action.has_value());
    EXPECT_EQ(action->operation, ActionOperation::split);
}

TEST(ScenarioRuntime, RejectedResetQueryRestartsTheCurrentPhaseRulesEvenWithoutAStateChange) {
    for (const auto phase : {TimerPhase::running, TimerPhase::paused, TimerPhase::ended}) {
        SCOPED_TRACE(to_string(phase));
        Scenario scenario;
        scenario.start_condition = invisible();
        scenario.incomplete_condition = std::make_shared<OnceCondition>(visible());
        scenario.splits.push_back(std::vector<ScenarioRulePtr>{std::make_shared<RuleSequence>(
            std::vector<std::shared_ptr<Rule>>{
                std::make_shared<Rule>(std::make_shared<OnceCondition>(visible()), Action{ActionOperation::split}),
                std::make_shared<Rule>(visible(), Action{ActionOperation::pause}),
            }
        )});
        ScenarioRuntime runtime{std::move(scenario)};
        const auto baseline = update(UpdateKind::initial, phase, phase == TimerPhase::ended ? 2 : 0, 2);
        runtime.apply_update(baseline);
        test::ManualTimeProvider clock;
        const auto normal = runtime.evaluate(white_frame(clock));
        ASSERT_TRUE(normal.has_value());
        runtime.action_accepted(*normal, clock.now());
        const auto reset = runtime.request_reset();
        ASSERT_TRUE(reset.has_value());
        auto queried = baseline;
        queried.kind = UpdateKind::periodic;
        runtime.settle_rejected_reset(queried);
        EXPECT_FALSE(runtime.action_pending(*reset));
        EXPECT_FALSE(runtime.action_pending(*normal));
        EXPECT_FALSE(runtime.state_wait_deadline().has_value());
        EXPECT_EQ(runtime.current_snapshot(), std::optional{baseline.snapshot});
        const auto fresh = runtime.evaluate(white_frame(clock));
        ASSERT_TRUE(fresh.has_value());
        EXPECT_EQ(fresh->operation, normal->operation);
    }
}

TEST(ScenarioRuntime, RejectedResetQueryRearmsAutomaticResetCondition) {
    Scenario scenario;
    scenario.start_condition = invisible();
    scenario.reset_condition = std::make_shared<OnceCondition>(visible());
    ScenarioRuntime runtime{std::move(scenario)};
    runtime.apply_update(update(UpdateKind::initial, TimerPhase::running, 0, 2));
    test::ManualTimeProvider clock;
    const auto reset = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(reset.has_value());
    ASSERT_EQ(reset->operation, ActionOperation::reset);
    runtime.settle_rejected_reset(update(UpdateKind::periodic, TimerPhase::running, 0, 2));
    EXPECT_FALSE(runtime.action_pending(*reset));
    const auto fresh = runtime.evaluate(white_frame(clock));
    ASSERT_TRUE(fresh.has_value());
    EXPECT_EQ(fresh->operation, ActionOperation::reset);
}
