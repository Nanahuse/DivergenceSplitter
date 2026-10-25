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
    EXPECT_TRUE(runtime.evaluate(white_frame(clock)).has_value());
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());

    clock.advance(std::chrono::milliseconds{1100});
    EXPECT_FALSE(runtime.evaluate(white_frame(clock)).has_value());
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
    ASSERT_EQ(condition.children.size(), 2U);
    EXPECT_EQ(condition.children[0].type, "detected");
    EXPECT_EQ(condition.children[0].status, "true");
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
