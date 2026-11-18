#include <gtest/gtest.h>

#include <algorithm>
#include <memory>
#include <stdexcept>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
#include "divergencesplitter/runtime/evaluation_history.hpp"
#include "divergencesplitter/runtime/scenario_runtime.hpp"
#include "test_support.hpp"

using namespace divergencesplitter;
using namespace std::chrono_literals;

namespace {
ConditionPtr detected(double threshold = 0.5) {
    return std::make_shared<DetectedCondition>(std::make_shared<MeanBrightnessDetector>(), threshold);
}
struct HistoryHarness {
    std::shared_ptr<test::ManualTimeProvider> clock = std::make_shared<test::ManualTimeProvider>();
    std::shared_ptr<EvaluationHistory> history = std::make_shared<EvaluationHistory>(clock);
    ConditionPtr root;
    explicit HistoryHarness(ConditionPtr condition) : root(std::move(condition)) { history->bind(root.get(), "root"); }
    void evaluate(int brightness, std::chrono::nanoseconds advance = 100ms, bool short_circuited = false) {
        clock->advance(advance);
        auto frame = test::make_context(test::solid(2, 2, brightness), *clock);
        history->begin_frame(clock->now());
        (void)root->evaluate(frame, short_circuited);
        history->end_frame();
    }
    ConditionHistory series(const std::string& path = "root") const {
        const auto snapshot = history->snapshot();
        const auto found = std::ranges::find(snapshot->conditions, path, &ConditionHistory::path);
        if (found == snapshot->conditions.end()) throw std::logic_error("missing history path");
        return *found;
    }
};
std::vector<double> values(const ConditionHistory& history) {
    std::vector<double> result;
    for (const auto& sample : history.samples) if (sample.value) result.push_back(*sample.value);
    return result;
}
LiveSplitUpdate state(TimerPhase phase, int split, std::uint32_t session = 1, std::uint64_t revision = 1) {
    LiveSplitUpdate update;
    update.kind = UpdateKind::resync;
    update.snapshot = {session, revision, 1, phase, split, 2};
    return update;
}
}

TEST(EvaluationHistory, RecordsEveryMeasuredScoreIncludingZeroWithoutPolling) {
    HistoryHarness harness{detected()};
    harness.evaluate(0, 10ms);
    harness.evaluate(255, 10ms);
    harness.evaluate(0, 10ms);
    const auto samples = harness.series().samples;
    ASSERT_EQ(samples.size(), 3);
    EXPECT_EQ(samples[0].value, 0.0);
    EXPECT_EQ(samples[1].value, 1.0);
    EXPECT_EQ(samples[2].value, 0.0);
    EXPECT_EQ(samples[1].time.nanoseconds, 20'000'000);
    EXPECT_EQ(condition_measurement(*harness.root).target, 0.5);
}

TEST(EvaluationHistory, ShortCircuitDoesNotRepeatPreviousScore) {
    HistoryHarness harness{std::make_shared<AllCondition>(std::vector<ConditionPtr>{detected(), detected()})};
    harness.evaluate(255);
    harness.evaluate(0);
    harness.evaluate(0);
    harness.evaluate(255);
    const auto samples = harness.series("root.c1").samples;
    ASSERT_EQ(samples.size(), 3);
    EXPECT_EQ(samples[0].value, 1.0);
    EXPECT_EQ(samples[1].event, HistoryEvent::gap);
    EXPECT_FALSE(samples[1].value);
    EXPECT_EQ(samples[2].value, 1.0);
}

TEST(EvaluationHistory, HoldKeepsFailedAttemptAndRestart) {
    HistoryHarness harness{std::make_shared<HoldCondition>(detected(), 1s)};
    harness.evaluate(255);
    harness.evaluate(255, 400ms);
    harness.evaluate(0, 100ms);
    harness.evaluate(255, 100ms);
    harness.evaluate(255, 300ms);
    const auto result = values(harness.series());
    ASSERT_EQ(result.size(), 5);
    EXPECT_DOUBLE_EQ(result[0], 0);
    EXPECT_DOUBLE_EQ(result[1], 0.4);
    EXPECT_DOUBLE_EQ(result[2], 0);
    EXPECT_DOUBLE_EQ(result[3], 0);
    EXPECT_DOUBLE_EQ(result[4], 0.3);
}

TEST(EvaluationHistory, SkippedParentStillRecordsActualChildAndNumericUpdates) {
    HistoryHarness harness{std::make_shared<AllCondition>(std::vector<ConditionPtr>{
        detected(), std::make_shared<HoldCondition>(std::make_shared<NotCondition>(detected()), 1s),
        std::make_shared<ElapsedCondition>(1s), std::make_shared<NthCondition>(std::make_shared<NotCondition>(detected()), 10)})};
    harness.evaluate(0);
    harness.evaluate(0, 250ms);
    const auto hold = harness.series("root.c1").samples;
    EXPECT_EQ(hold.back().status, ConditionStatus::skipped);
    EXPECT_EQ(hold.back().value, 0.25);
    EXPECT_EQ(harness.series("root.c1.c0.c0").samples.back().value, 0.0);
    EXPECT_EQ(harness.series("root.c2").samples.back().value, 0.25);
    EXPECT_EQ(harness.series("root.c3").samples.back().value, 2.0);
}

TEST(EvaluationHistory, ElapsedCompletionGapAndResetRemainDistinct) {
    HistoryHarness harness{std::make_shared<ElapsedCondition>(500ms)};
    harness.evaluate(0);
    harness.evaluate(0, 500ms);
    harness.clock->advance(100ms);
    harness.history->begin_frame(harness.clock->now());
    harness.history->end_frame();
    harness.evaluate(0);
    harness.root->reset();
    harness.evaluate(0);
    const auto samples = harness.series().samples;
    ASSERT_EQ(samples.size(), 6);
    EXPECT_EQ(samples[1].value, 0.5);
    EXPECT_EQ(samples[1].result, true);
    EXPECT_EQ(samples[2].event, HistoryEvent::gap);
    EXPECT_FALSE(samples[2].value);
    EXPECT_EQ(samples[3].value, 0.5);
    EXPECT_EQ(samples[4].event, HistoryEvent::reset);
    EXPECT_EQ(samples[5].value, 0.0);
}

TEST(EvaluationHistory, NthCountsTrueEvaluationsRatherThanEdgesAndRecordsReset) {
    HistoryHarness harness{std::make_shared<NthCondition>(detected(), 3)};
    harness.evaluate(255);
    harness.evaluate(255);
    harness.evaluate(0);
    harness.evaluate(255);
    EXPECT_EQ(values(harness.series()), (std::vector<double>{1, 2, 2, 3}));
    harness.root->reset();
    EXPECT_EQ(harness.series().samples.back().event, HistoryEvent::reset);
    harness.evaluate(0);
    EXPECT_EQ(harness.series().samples.back().value, 0.0);
}

TEST(EvaluationHistory, NthWithRisingEdgeCountsOnlyFiredEdges) {
    HistoryHarness harness{std::make_shared<NthCondition>(std::make_shared<RisingEdgeCondition>(detected()), 3)};
    for (const int value : {0, 255, 255, 0, 255}) harness.evaluate(value);
    EXPECT_EQ(values(harness.series()), (std::vector<double>{0, 1, 1, 1, 2}));
}

TEST(EvaluationHistory, ThenRetainsInactiveStepsAndCompletionTransition) {
    HistoryHarness harness{std::make_shared<ThenCondition>(std::vector<ConditionPtr>{detected(), detected()}, std::nullopt)};
    harness.evaluate(255);
    harness.evaluate(0);
    harness.evaluate(255);
    const auto first = harness.series("root.c0").samples;
    ASSERT_EQ(first.size(), 2);
    EXPECT_EQ(first[0].value, 1.0);
    EXPECT_EQ(first[1].event, HistoryEvent::gap);
    EXPECT_EQ(values(harness.series()), (std::vector<double>{1, 1, 2}));
    EXPECT_EQ(harness.series().samples.back().event, HistoryEvent::transition);
    EXPECT_EQ(values(harness.series("root.c1")), (std::vector<double>{0, 1}));
}

TEST(EvaluationHistory, ResetWhenRecordsResetAndReevaluationAtSameTimestamp) {
    HistoryHarness harness{std::make_shared<ResetWhenCondition>(
        std::make_shared<NthCondition>(detected(), 4), detected())};
    harness.evaluate(255);
    const auto samples = harness.series("root.c0").samples;
    ASSERT_EQ(samples.size(), 2);
    EXPECT_EQ(samples[0].event, HistoryEvent::reset);
    EXPECT_EQ(samples[1].value, 1.0);
    EXPECT_EQ(samples[0].time, samples[1].time);
}

TEST(EvaluationHistory, ThenTimeoutRecordsBoundaryEvenWhenItReentersTheSameStep) {
    HistoryHarness harness{std::make_shared<ThenCondition>(
        std::vector<ConditionPtr>{detected(), detected(2.0)}, 200ms)};
    harness.evaluate(255);
    harness.evaluate(255, 300ms);
    const auto samples = harness.series().samples;
    ASSERT_EQ(samples.size(), 3);
    EXPECT_EQ(samples[0].value, 1.0);
    EXPECT_EQ(samples[1].event, HistoryEvent::reset);
    EXPECT_EQ(samples[2].value, 1.0);
    EXPECT_EQ(samples[1].time, samples[2].time);
}

TEST(EvaluationHistory, OnceCompletionPersistsWhileItsChildIsSkipped) {
    HistoryHarness harness{std::make_shared<OnceCondition>(detected())};
    harness.evaluate(255);
    harness.evaluate(0);
    const auto samples = harness.series().samples;
    EXPECT_EQ(samples[0].result, true);
    EXPECT_EQ(samples[1].result, true);
    EXPECT_EQ(samples[1].value, 1.0);
    EXPECT_EQ(harness.series("root.c0").samples.back().event, HistoryEvent::gap);
}

TEST(EvaluationHistory, FallingEdgeRecordsChildStateAndFiredEvent) {
    HistoryHarness harness{std::make_shared<FallingEdgeCondition>(detected())};
    for (const int value : {255, 255, 0, 0}) harness.evaluate(value);
    EXPECT_EQ(values(harness.series()), (std::vector<double>{0, 0, 1, 0}));
    EXPECT_EQ(values(harness.series("root.c0")), (std::vector<double>{1, 1, 0, 0}));
}

TEST(EvaluationHistory, ErrorsDoNotRepeatAStaleScoreAndOriginalExceptionSurvives) {
    HistoryHarness harness{detected()};
    harness.evaluate(255);
    auto invalid_frame = test::make_context(cv::Mat{}, *harness.clock);
    harness.history->begin_frame(harness.clock->now());
    EXPECT_ANY_THROW((void)harness.root->evaluate(invalid_frame));
    harness.history->end_frame();
    const auto samples = harness.series().samples;
    ASSERT_EQ(samples.size(), 2);
    EXPECT_EQ(samples[1].event, HistoryEvent::error);
    EXPECT_FALSE(samples[1].value);
}

TEST(EvaluationHistory, ObserverFailureCannotChangeEvaluationOrReset) {
    const auto condition = detected();
    condition->set_observer([](const auto&, auto, auto, auto, auto) { throw std::runtime_error("diagnostics failure"); });
    test::ManualTimeProvider clock;
    auto frame = test::make_context(test::solid(2, 2, 255), clock);
    EXPECT_EQ(condition->evaluate(frame), true);
    EXPECT_NO_THROW(condition->reset());
}

TEST(EvaluationHistory, BoundedRetentionPreservesIsolatedSpikeAndExpiresAtSixtySeconds) {
    HistoryHarness harness{detected()};
    for (std::size_t i = 0; i < EvaluationHistory::capacity + 100; ++i)
        harness.evaluate(i == 3000 ? 255 : 0, 1ms);
    const auto samples = harness.series().samples;
    EXPECT_LE(samples.size(), EvaluationHistory::capacity);
    EXPECT_TRUE(std::ranges::any_of(samples, [](const auto& sample) { return sample.value == 1.0; }));
    harness.clock->advance(61s);
    EXPECT_TRUE(harness.series().samples.empty());
    harness.evaluate(0);
    EXPECT_EQ(harness.series().samples.size(), 1);
}

TEST(EvaluationHistory, RuntimeKeepsRulesDistinctAndOptInSnapshotsImmutable) {
    const auto clock = std::make_shared<test::ManualTimeProvider>();
    Scenario scenario;
    scenario.start_condition = detected();
    scenario.reset_condition = detected(2.0);
    scenario.splits.push_back(std::vector<ScenarioRulePtr>{std::make_shared<Rule>(detected(3.0), Action{ActionOperation::split})});
    ScenarioRuntime runtime{scenario, clock};
    runtime.apply_update(state(TimerPhase::running, 0));
    auto frame = test::make_context(test::solid(2, 2, 255), *clock);
    EXPECT_FALSE(runtime.evaluate(frame));
    EXPECT_FALSE(runtime.diagnostics().history);
    const auto before = runtime.diagnostics(true);
    ASSERT_TRUE(before.history);
    const auto reset = std::ranges::find(before.history->conditions, "reset.r0.cond", &ConditionHistory::path);
    const auto split = std::ranges::find(before.history->conditions, "split.0.r0.cond", &ConditionHistory::path);
    ASSERT_NE(reset, before.history->conditions.end());
    ASSERT_NE(split, before.history->conditions.end());
    EXPECT_EQ(reset->samples.back().value, 1.0);
    EXPECT_EQ(split->samples.back().value, 1.0);
    clock->advance(100ms);
    runtime.apply_update(state(TimerPhase::not_running, -1, 1, 2));
    EXPECT_EQ(runtime.diagnostics(true).history->identity, before.history->identity);
    EXPECT_EQ(split->samples.back().value, 1.0); // Old UI snapshots are immutable.
    runtime.apply_update(state(TimerPhase::not_running, -1, 2, 3));
    EXPECT_NE(runtime.diagnostics(true).history->identity, before.history->identity);
    ScenarioRuntime replacement{scenario, clock};
    EXPECT_NE(replacement.diagnostics(true).history->identity, runtime.diagnostics(true).history->identity);
}

TEST(EvaluationHistory, SharedFrameDoesNotShareInstanceHistory) {
    HistoryHarness first{detected(0.5)}, second{detected(2.0)};
    auto frame = test::make_context(test::solid(2, 2, 255), *first.clock);
    first.history->begin_frame(frame.now());
    second.history->begin_frame(frame.now());
    EXPECT_EQ(first.root->evaluate(frame), true);
    EXPECT_EQ(second.root->evaluate(frame), false);
    first.history->end_frame();
    second.history->end_frame();
    EXPECT_NE(first.history->snapshot()->identity, second.history->snapshot()->identity);
    EXPECT_EQ(first.series().samples.back().result, true);
    EXPECT_EQ(second.series().samples.back().result, false);
}

TEST(EvaluationHistory, SelectedSnapshotsDoNotCopyOtherPathsOrDiscardTheirSamples) {
    HistoryHarness harness{std::make_shared<AllCondition>(std::vector<ConditionPtr>{detected(2.0),
        std::make_shared<HoldCondition>(detected(), 1s)})};
    harness.evaluate(255);
    harness.evaluate(255);
    HistoryPaths paths{"root.c0"};
    const auto selected = harness.history->snapshot(&paths);
    ASSERT_EQ(selected->conditions.size(), 1);
    EXPECT_EQ(selected->conditions[0].path, "root.c0");
    const auto full = harness.history->snapshot();
    EXPECT_EQ(full->identity, selected->identity);
    EXPECT_EQ(full->conditions.size(), 4);
    EXPECT_EQ(harness.series("root.c1").samples.size(), 2);
    paths.clear();
    EXPECT_TRUE(harness.history->snapshot(&paths)->conditions.empty());
    paths.insert("root.c1");
    const auto reopened = harness.history->snapshot(&paths);
    ASSERT_EQ(reopened->conditions.size(), 1);
    EXPECT_EQ(reopened->conditions[0].samples.size(), 2);
}

TEST(EvaluationHistory, ThenDiagnosticsExposeCurrentCompletionTimeoutAndResetWithoutReevaluation) {
    auto clock = std::make_shared<test::ManualTimeProvider>();
    Scenario scenario;
    scenario.start_condition = std::make_shared<ThenCondition>(
        std::vector<ConditionPtr>{detected(), std::make_shared<ElapsedCondition>(100ms)}, std::nullopt);
    ScenarioRuntime runtime{scenario, clock};
    runtime.apply_update(state(TimerPhase::not_running, -1));
    const auto inspect = [&] { return runtime.diagnostics().start[0].rules[0].condition; };
    const auto evaluate = [&](int gray) {
        return runtime.evaluate(test::make_context(test::solid(2, 2, gray), *clock));
    };
    EXPECT_EQ(inspect().active_step, 0);
    (void)evaluate(255);
    EXPECT_EQ(inspect().active_step, 1);
    clock->advance(50ms);
    (void)evaluate(255);
    EXPECT_FALSE(inspect().completed);
    clock->advance(100ms);
    EXPECT_TRUE(evaluate(255));
    EXPECT_TRUE(inspect().completed);
    EXPECT_FALSE(inspect().active_step);
    runtime.apply_update(state(TimerPhase::running, 0, 1, 2));
    runtime.apply_update(state(TimerPhase::not_running, -1, 1, 3));
    EXPECT_FALSE(inspect().completed);
    EXPECT_EQ(inspect().active_step, 0);

    Scenario timed;
    timed.start_condition = std::make_shared<ThenCondition>(
        std::vector<ConditionPtr>{detected(), detected(2.0)}, 200ms);
    ScenarioRuntime timeout{timed, clock};
    timeout.apply_update(state(TimerPhase::not_running, -1));
    (void)timeout.evaluate(test::make_context(test::solid(2, 2, 255), *clock));
    EXPECT_EQ(timeout.diagnostics().start[0].rules[0].condition.active_step, 1);
    clock->advance(300ms);
    (void)timeout.evaluate(test::make_context(test::solid(2, 2, 0), *clock));
    EXPECT_EQ(timeout.diagnostics().start[0].rules[0].condition.active_step, 0);
}


TEST(EvaluationHistory, RecentSnapshotExcludesResetOnlyAndExpiredSeriesButKeepsExplicitHistory) {
    auto clock = std::make_shared<test::ManualTimeProvider>();
    auto history = std::make_shared<EvaluationHistory>(clock);
    auto old = detected(), current = detected(), unopened = detected();
    history->bind(old.get(), "old");
    history->bind(current.get(), "current");
    history->bind(unopened.get(), "unopened");
    const auto evaluate = [&](const ConditionPtr& node) {
        history->begin_frame(clock->now());
        auto frame = test::make_context(test::solid(2, 2, 255), *clock);
        (void)node->evaluate(frame);
        history->end_frame();
    };
    evaluate(old);
    clock->advance(40s);
    old->reset();
    unopened->reset();
    evaluate(current);
    const HistoryPaths selected{"old"};
    const auto recent = history->snapshot(nullptr, 30s);
    ASSERT_EQ(recent->conditions.size(), 1);
    EXPECT_EQ(recent->conditions.front().path, "current");
    EXPECT_EQ(recent->conditions.front().last_observation, clock->now());
    const auto detail = history->snapshot(&selected, 30s);
    ASSERT_EQ(detail->conditions.size(), 2);
    EXPECT_EQ(detail->conditions[0].path, "old");
    EXPECT_EQ(detail->conditions[0].samples.front().result, true);
    EXPECT_EQ(history->snapshot(nullptr, 60s)->conditions.size(), 2);
    clock->advance(61s);
    EXPECT_TRUE(history->snapshot(nullptr, 60s)->conditions.empty());
}

TEST(EvaluationHistory, TimerResetBoundarySurvivesWithoutResetRulesUntilSessionChanges) {
    auto clock = std::make_shared<test::ManualTimeProvider>();
    Scenario scenario;
    scenario.start_condition = detected();
    ScenarioRuntime runtime{scenario, clock};
    runtime.apply_update(state(TimerPhase::running, 0));
    const auto identity = runtime.diagnostics(true).history->identity;
    clock->advance(1s);
    runtime.apply_update(state(TimerPhase::not_running, -1, 1, 2));
    const auto reset = runtime.diagnostics(true, nullptr, 15s).history;
    EXPECT_EQ(reset->identity, identity);
    ASSERT_EQ(reset->timer_resets.size(), 1);
    EXPECT_EQ(reset->timer_resets.front(), clock->now());
    clock->advance(16s);
    EXPECT_TRUE(runtime.diagnostics(true, nullptr, 15s).history->timer_resets.empty());
    EXPECT_EQ(runtime.diagnostics(true, nullptr, 30s).history->timer_resets.size(), 1);
    runtime.apply_update(state(TimerPhase::not_running, -1, 2));
    EXPECT_NE(runtime.diagnostics(true).history->identity, identity);
    EXPECT_TRUE(runtime.diagnostics(true).history->timer_resets.empty());
}

TEST(EvaluationHistory, DensePreviewKeepsExtremaAndGapsWhileInspectorRetainsRawSamples) {
    auto clock = std::make_shared<test::ManualTimeProvider>();
    auto history = std::make_shared<EvaluationHistory>(clock);
    auto score = detected(2);
    history->bind(score.get(), "score");
    std::vector<ConditionPtr> dense;
    for (int i = 0; i < 35; ++i) {
        dense.push_back(std::make_shared<ElapsedCondition>(120s));
        history->bind(dense.back().get(), "elapsed." + std::to_string(i));
    }
    for (int i = 0; i < 6020; ++i) {
        clock->advance(10ms);
        history->begin_frame(clock->now());
        auto frame = test::make_context(test::solid(2, 2, i == 4001 ? 255 : 50), *clock);
        for (const auto& node : dense) (void)node->evaluate(frame);
        if (i == 4004) score->mark_skipped();
        else (void)score->evaluate(frame);
        history->end_frame();
    }
    const auto preview = history->snapshot(nullptr, 60s);
    const HistoryPaths selected{"score"};
    const auto inspector = history->snapshot(&selected);
    ASSERT_EQ(preview->conditions.size(), 36);
    ASSERT_EQ(inspector->conditions.size(), 1);
    const auto& samples = preview->conditions.front().samples;
    EXPECT_LT(samples.size(), 500);
    EXPECT_GE(inspector->conditions.front().samples.size(), 6000);
    EXPECT_EQ(samples.front().time, inspector->conditions.front().samples.front().time);
    EXPECT_EQ(samples.back().time, inspector->conditions.front().samples.back().time);
    EXPECT_TRUE(std::ranges::any_of(samples, [](const auto& sample) { return sample.value == 1; }));
    EXPECT_TRUE(std::ranges::any_of(samples, [](const auto& sample) { return sample.event == HistoryEvent::gap; }));
    const auto combined = history->snapshot(&selected, 60s);
    const auto& detail = combined->conditions.front();
    ASSERT_TRUE(detail.preview_samples);
    const auto same = [](const auto& a, const auto& b) {
        return a.time == b.time && a.value == b.value && a.status == b.status &&
            a.event == b.event && a.result == b.result;
    };
    EXPECT_TRUE(std::ranges::equal(*detail.preview_samples, samples, same));
    EXPECT_TRUE(std::ranges::equal(detail.samples, inspector->conditions.front().samples, same));
}
