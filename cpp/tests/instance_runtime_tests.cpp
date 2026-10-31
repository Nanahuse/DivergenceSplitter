#include <gtest/gtest.h>

#include <chrono>
#include <atomic>
#include <functional>
#include <memory>
#include <thread>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
#include "divergencesplitter/livesplit/adapter.hpp"
#include "divergencesplitter/runtime/instance_runtime.hpp"
#include "test_support.hpp"

using namespace divergencesplitter;
using namespace std::chrono_literals;

namespace {

ConditionPtr visible() {
    return std::make_shared<DetectedCondition>(
        std::make_shared<MeanBrightnessDetector>(),
        0.5
    );
}

std::shared_ptr<SharedFrameEvaluation> frame_with_gray(int gray) {
    const auto now = monotonic_now();
    return std::make_shared<SharedFrameEvaluation>(
        SharedFrameEvaluation{
            Frame{test::solid(4, 4, gray), now},
            now,
            {},
        }
    );
}

std::shared_ptr<SharedFrameEvaluation> white_frame() {
    return frame_with_gray(255);
}

void pump(
    InstanceRuntime& runtime,
    const std::function<bool()>& done,
    std::chrono::milliseconds timeout = 3s
) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        if (done()) {
            return;
        }
        runtime.publish_frame(white_frame());
        std::this_thread::sleep_for(5ms);
    }
}

Scenario split_scenario(bool automatic_reset = false) {
    Scenario scenario;
    scenario.start_condition = std::make_shared<NotCondition>(visible());
    if (automatic_reset) {
        scenario.reset_condition = std::make_shared<NotCondition>(visible());
    }
    scenario.splits.push_back(std::vector<ScenarioRulePtr>{
        std::make_shared<Rule>(visible(), Action{ActionOperation::split}),
    });
    scenario.splits.push_back(std::nullopt);
    return scenario;
}

bool pending(const InstanceRuntime& runtime, ActionOperation operation) {
    const auto diagnostics = runtime.diagnostics();
    return diagnostics.scenario.has_value() &&
           (diagnostics.scenario->pending_action == operation ||
            diagnostics.scenario->reset_pending == operation);
}

BridgeEvent timer_event(TimerPhase phase, int index) {
    BridgeEvent event;
    event.session_id = 1;
    event.kind = phase == TimerPhase::not_running ? BridgeEventKind::reset : BridgeEventKind::timer;
    event.phase = phase;
    event.split_index = index;
    return event;
}

}  // namespace

TEST(InstanceRuntime, ExecutesStartWhenNotRunning) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::not_running, -1, 2)
    );
    auto* bridge = fake.get();
    bridge->on_execute = [bridge](ActionOperation operation) {
        if (operation == ActionOperation::start) {
            bridge->set_snapshot(test::make_snapshot(TimerPhase::running, 0, 2));
        }
        return BridgeControlResult{BridgeControlStatus::ok, {}};
    };

    Scenario scenario;
    scenario.start_condition = visible();
    InstanceRuntime runtime{0, std::move(scenario), std::move(fake)};
    runtime.start();

    pump(runtime, [&]() { return !bridge->actions().empty(); });
    ASSERT_EQ(bridge->actions().size(), 1U);
    EXPECT_EQ(bridge->actions().front(), ActionOperation::start);
    const auto diagnostics = runtime.diagnostics();
    EXPECT_EQ(diagnostics.state, InstanceState::ready);
    ASSERT_TRUE(diagnostics.last_action.has_value());
    EXPECT_EQ(*diagnostics.last_action, ActionOperation::start);

    runtime.stop();
    EXPECT_EQ(runtime.state(), InstanceState::stopped);
}

TEST(InstanceRuntime, LatestPublishedFrameWins) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::not_running, -1, 2)
    );
    auto* bridge = fake.get();
    bridge->on_execute = [bridge](ActionOperation operation) {
        if (operation == ActionOperation::start) {
            bridge->set_snapshot(test::make_snapshot(TimerPhase::running, 0, 2));
        }
        return BridgeControlResult{BridgeControlStatus::ok, {}};
    };

    Scenario scenario;
    scenario.start_condition = visible();
    InstanceRuntime runtime{0, std::move(scenario), std::move(fake)};
    runtime.publish_frame(frame_with_gray(0));
    runtime.publish_frame(frame_with_gray(255));
    runtime.start();

    pump(runtime, [&]() { return !bridge->actions().empty(); });
    ASSERT_EQ(bridge->actions().size(), 1U);
    EXPECT_EQ(bridge->actions().front(), ActionOperation::start);
    runtime.stop();
}

TEST(InstanceRuntime, ExecutesSplitForCurrentIndex) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    bridge->on_execute = [bridge](ActionOperation operation) {
        if (operation == ActionOperation::split) {
            bridge->set_snapshot(test::make_snapshot(TimerPhase::running, 1, 2));
        }
        return BridgeControlResult{BridgeControlStatus::ok, {}};
    };

    Scenario scenario;
    scenario.start_condition = visible();
    scenario.splits.push_back(
        std::vector<ScenarioRulePtr>{std::make_shared<Rule>(
            visible(),
            Action{ActionOperation::split}
        )}
    );
    scenario.splits.push_back(std::nullopt);
    InstanceRuntime runtime{0, std::move(scenario), std::move(fake)};
    runtime.start();

    pump(runtime, [&]() { return !bridge->actions().empty(); });
    ASSERT_EQ(bridge->actions().size(), 1U);
    EXPECT_EQ(bridge->actions().front(), ActionOperation::split);

    runtime.stop();
}

TEST(InstanceRuntime, ManualResetUsesInstanceThread) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    bridge->on_execute = [bridge](ActionOperation operation) {
        if (operation == ActionOperation::reset) {
            bridge->set_snapshot(test::make_snapshot(TimerPhase::not_running, -1, 2));
        }
        return BridgeControlResult{BridgeControlStatus::ok, {}};
    };

    Scenario scenario;
    scenario.start_condition = std::make_shared<NotCondition>(visible());
    InstanceRuntime runtime{0, std::move(scenario), std::move(fake)};
    runtime.start();
    ASSERT_TRUE(test::wait_until([&]() {
        return runtime.diagnostics().state == InstanceState::ready;
    }));
    runtime.request_manual_reset();

    pump(runtime, [&]() { return !bridge->actions().empty(); });
    ASSERT_EQ(bridge->actions().size(), 1U);
    EXPECT_EQ(bridge->actions().front(), ActionOperation::reset);

    runtime.stop();
}

TEST(InstanceRuntime, UnknownControlIsNotAutomaticallyResent) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::not_running, -1, 2)
    );
    auto* bridge = fake.get();
    bridge->on_execute = [](ActionOperation) {
        return BridgeControlResult{BridgeControlStatus::unknown, "unknown"};
    };

    Scenario scenario;
    scenario.start_condition = visible();
    InstanceRuntime runtime{0, std::move(scenario), std::move(fake)};
    runtime.start();

    pump(runtime, [&]() { return !bridge->actions().empty(); });
    ASSERT_EQ(bridge->actions().size(), 1U);
    pump(runtime, []() { return false; }, 300ms);
    EXPECT_EQ(bridge->actions().size(), 1U);

    runtime.stop();
}

TEST(Adapter, TimerEventUpdatesStateWithoutQuery) {
    test::FakeBridgeClient client{test::make_snapshot(TimerPhase::running, 0, 2)};
    LiveSplitBridgeAdapter adapter{client};
    (void)adapter.attach();
    EXPECT_EQ(client.sync_count(), 1U);

    BridgeEvent event;
    event.kind = BridgeEventKind::timer;
    event.session_id = 1;
    event.phase = TimerPhase::paused;
    event.split_index = 2;
    const auto update = adapter.apply_event(event);
    ASSERT_TRUE(update.has_value());
    EXPECT_EQ(update->snapshot.phase, TimerPhase::paused);
    EXPECT_EQ(update->snapshot.split_index, 2);
    EXPECT_EQ(client.sync_count(), 1U);
}

TEST(Adapter, ContextEventDoesNotQuery) {
    test::FakeBridgeClient client{test::make_snapshot(TimerPhase::running, 0, 2)};
    LiveSplitBridgeAdapter adapter{client};
    (void)adapter.attach();
    BridgeEvent event;
    event.kind = BridgeEventKind::context_changed;
    event.session_id = 1;
    EXPECT_FALSE(adapter.apply_event(event).has_value());
    EXPECT_EQ(client.sync_count(), 1U);
}

TEST(InstanceRuntime, TimerEventDoesNotBlockOnSnapshotQuery) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();

    Scenario scenario;
    scenario.start_condition = visible();
    InstanceRuntime runtime{0, std::move(scenario), std::move(fake)};
    runtime.start();
    ASSERT_TRUE(test::wait_until([&]() {
        return runtime.diagnostics().state == InstanceState::ready;
    }));
    const auto baseline_syncs = bridge->sync_count();
    BridgeEvent event;
    event.kind = BridgeEventKind::timer;
    event.session_id = 1;
    event.phase = TimerPhase::paused;
    event.split_index = 1;
    bridge->push_event(event);
    ASSERT_TRUE(test::wait_until([&]() {
        const auto diagnostics = runtime.diagnostics();
        return diagnostics.scenario.has_value() &&
               diagnostics.scenario->snapshot.has_value() &&
               diagnostics.scenario->snapshot->phase == TimerPhase::paused;
    }));
    EXPECT_EQ(bridge->sync_count(), baseline_syncs);
    runtime.stop();
}

TEST(InstanceRuntime, ReconnectsAfterConnectionLoss) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();

    Scenario scenario;
    scenario.start_condition = visible();
    InstanceRuntime runtime{0, std::move(scenario), std::move(fake)};
    runtime.start();
    ASSERT_TRUE(test::wait_until([&]() { return runtime.diagnostics().state == InstanceState::ready; }));

    bridge->set_ready(false);
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() {
        return runtime.diagnostics().state == InstanceState::connecting;
    }));

    bridge->set_snapshot(test::make_snapshot(TimerPhase::running, 1, 2, 2));
    bridge->set_ready(true);
    ASSERT_TRUE(test::wait_until([&]() {
        return runtime.diagnostics().state == InstanceState::ready;
    }));

    runtime.stop();
}

TEST(InstanceRuntime, UnrelatedEventsDoNotCancelReactionWait) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    InstanceRuntime runtime{0, split_scenario(), std::move(fake), {300ms}};
    runtime.start();
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() { return pending(runtime, ActionOperation::split); }));
    ASSERT_TRUE(bridge->actions().empty());
    BridgeEvent event;
    event.session_id = 1;
    event.kind = BridgeEventKind::context_changed;
    bridge->push_event(event);
    event.kind = BridgeEventKind::other;
    bridge->push_event(event);

    ASSERT_TRUE(test::wait_until([&]() { return runtime.diagnostics().action_count == 1; }));
    EXPECT_EQ(bridge->actions(), std::vector{ActionOperation::split});
    EXPECT_EQ(bridge->sync_count(), 2U);  // Attach and the "other" event only.
    runtime.stop();
}

TEST(InstanceRuntime, ManualResetCancelsUnsentSplitWithoutAnotherFrame) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    InstanceRuntime runtime{0, split_scenario(), std::move(fake), {500ms}};
    runtime.start();
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() { return pending(runtime, ActionOperation::split); }));
    ASSERT_TRUE(bridge->actions().empty());
    runtime.request_manual_reset();
    ASSERT_TRUE(test::wait_until([&]() { return pending(runtime, ActionOperation::reset); }));
    // A repeated request must not send another Reset while confirmation is pending.
    runtime.request_manual_reset();
    bridge->push_event(timer_event(TimerPhase::not_running, -1));
    ASSERT_TRUE(test::wait_until([&]() { return !pending(runtime, ActionOperation::reset); }));
    runtime.stop();
    EXPECT_EQ(bridge->actions(), std::vector{ActionOperation::reset});
}

TEST(InstanceRuntime, AutomaticResetIsEvaluatedDuringReactionWait) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    InstanceRuntime runtime{0, split_scenario(true), std::move(fake), {10s}};
    runtime.start();
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() { return pending(runtime, ActionOperation::split); }));
    runtime.publish_frame(frame_with_gray(0));
    // Reset must arrive well before either the original or a restarted 10s delay.
    ASSERT_TRUE(test::wait_until([&]() { return !bridge->actions().empty(); }, 1s));
    runtime.stop();
    EXPECT_EQ(bridge->actions(), std::vector{ActionOperation::reset});
}

TEST(InstanceRuntime, SuccessfulRpcWaitsForStateInsteadOfQueryingImmediately) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    InstanceRuntime runtime{0, split_scenario(), std::move(fake)};
    runtime.start();
    pump(runtime, [&]() { return runtime.diagnostics().action_count == 1; });
    pump(runtime, []() { return false; }, 200ms);
    EXPECT_EQ(bridge->actions(), std::vector{ActionOperation::split});
    EXPECT_EQ(bridge->sync_count(), 1U);
    EXPECT_TRUE(pending(runtime, ActionOperation::split));

    bridge->push_event(timer_event(TimerPhase::paused, 0));
    ASSERT_TRUE(test::wait_until([&]() {
        return runtime.diagnostics().scenario->snapshot->phase == TimerPhase::paused;
    }));
    EXPECT_TRUE(pending(runtime, ActionOperation::split));
    bridge->push_event(timer_event(TimerPhase::running, 0));
    bridge->push_event(timer_event(TimerPhase::running, 1));
    ASSERT_TRUE(test::wait_until([&]() { return !pending(runtime, ActionOperation::split); }));
    EXPECT_EQ(bridge->sync_count(), 1U);
    runtime.stop();
}

TEST(InstanceRuntime, ConfirmationTimeoutQueriesStateWithoutNewFrames) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    InstanceRuntime runtime{0, split_scenario(), std::move(fake)};
    runtime.start();
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() { return runtime.diagnostics().action_count == 1; }));
    EXPECT_TRUE(pending(runtime, ActionOperation::split));
    // Simulate a successful Split whose event was lost; no more input frames.
    bridge->set_snapshot(test::make_snapshot(TimerPhase::running, 1, 2));
    ASSERT_TRUE(test::wait_until([&]() { return !pending(runtime, ActionOperation::split); }));
    EXPECT_EQ(runtime.diagnostics().scenario->snapshot->split_index, 1);
    EXPECT_EQ(bridge->sync_count(), 2U);
    pump(runtime, []() { return false; }, 50ms);
    runtime.stop();
    EXPECT_EQ(bridge->actions(), std::vector{ActionOperation::split});
}

TEST(InstanceRuntime, LateSplitDoesNotReleaseManualResetConfirmation) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    InstanceRuntime runtime{0, split_scenario(), std::move(fake)};
    runtime.start();
    pump(runtime, [&]() { return runtime.diagnostics().action_count == 1; });
    runtime.request_manual_reset();
    ASSERT_TRUE(test::wait_until([&]() { return runtime.diagnostics().action_count == 2; }));
    bridge->push_event(timer_event(TimerPhase::running, 1));
    ASSERT_TRUE(test::wait_until([&]() {
        return runtime.diagnostics().scenario->snapshot->split_index == 1;
    }));
    EXPECT_TRUE(pending(runtime, ActionOperation::reset));
    runtime.request_manual_reset();
    pump(runtime, []() { return false; }, 50ms);
    runtime.stop();
    EXPECT_EQ(bridge->actions(), (std::vector{ActionOperation::split, ActionOperation::reset}));
}

TEST(InstanceRuntime, StopCancelsReactionWait) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    InstanceRuntime runtime{0, split_scenario(), std::move(fake), {500ms}};
    runtime.start();
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() { return pending(runtime, ActionOperation::split); }));
    runtime.stop();
    EXPECT_TRUE(bridge->actions().empty());
    EXPECT_EQ(runtime.state(), InstanceState::stopped);
}

TEST(Adapter, UnchangedQueryDoesNotInventATimerTransition) {
    test::FakeBridgeClient client{test::make_snapshot(TimerPhase::running, 0, 2)};
    LiveSplitBridgeAdapter adapter{client};
    const auto initial = adapter.attach();
    BridgeEvent event;
    event.session_id = 1;
    event.kind = BridgeEventKind::other;
    const auto update = adapter.apply_event(event);
    ASSERT_TRUE(update.has_value());
    EXPECT_EQ(update->snapshot, initial.snapshot);
}

TEST(InstanceRuntime, TimerTransitionCancelsUnsentSplit) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    InstanceRuntime runtime{0, split_scenario(), std::move(fake), {300ms}};
    runtime.start();
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() { return pending(runtime, ActionOperation::split); }));
    bridge->push_event(timer_event(TimerPhase::paused, 0));
    ASSERT_TRUE(test::wait_until([&]() {
        return runtime.diagnostics().last_action_result == "cancelled (state changed)";
    }));
    EXPECT_FALSE(pending(runtime, ActionOperation::split));
    runtime.stop();
    EXPECT_TRUE(bridge->actions().empty());
}

TEST(InstanceRuntime, RejectedManualResetQueriesAndRearmsTheSameSplit) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    bridge->on_execute = [](ActionOperation operation) {
        return operation == ActionOperation::reset
            ? BridgeControlResult{BridgeControlStatus::error, "reset rejected"}
            : BridgeControlResult{BridgeControlStatus::ok, {}};
    };
    auto scenario = split_scenario();
    scenario.splits[0] = std::vector<ScenarioRulePtr>{std::make_shared<RuleSequence>(
        std::vector<std::shared_ptr<Rule>>{
            std::make_shared<Rule>(std::make_shared<OnceCondition>(visible()), Action{ActionOperation::split}),
            std::make_shared<Rule>(visible(), Action{ActionOperation::pause}),
        }
    )};
    InstanceRuntime runtime{0, std::move(scenario), std::move(fake)};
    runtime.start();
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() { return runtime.diagnostics().action_count == 1; }));
    runtime.request_manual_reset();
    ASSERT_TRUE(test::wait_until([&]() {
        return bridge->sync_count() == 2 && !pending(runtime, ActionOperation::split) &&
            !pending(runtime, ActionOperation::reset);
    }));
    EXPECT_EQ(bridge->actions(), (std::vector{ActionOperation::split, ActionOperation::reset}));
    EXPECT_EQ(runtime.diagnostics().scenario->snapshot->split_index, 0);
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() { return runtime.diagnostics().action_count == 3; }));
    runtime.stop();
    EXPECT_EQ(bridge->actions(), (std::vector{ActionOperation::split, ActionOperation::reset, ActionOperation::split}));
}

TEST(InstanceRuntime, RejectedManualResetAdoptsTheQueriedSplitIndex) {
    auto fake = std::make_unique<test::FakeBridgeClient>(test::make_snapshot(TimerPhase::running, 0, 2));
    auto* bridge = fake.get();
    bridge->on_execute = [bridge](ActionOperation operation) {
        if (operation == ActionOperation::reset) {
            bridge->set_snapshot(test::make_snapshot(TimerPhase::running, 1, 2));
            return BridgeControlResult{BridgeControlStatus::error, "reset rejected"};
        }
        return BridgeControlResult{BridgeControlStatus::ok, {}};
    };
    auto scenario = split_scenario();
    scenario.splits[1] = std::vector<ScenarioRulePtr>{std::make_shared<Rule>(
        std::make_shared<OnceCondition>(visible()), Action{ActionOperation::skip})};
    InstanceRuntime runtime{0, std::move(scenario), std::move(fake)};
    runtime.start();
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() { return runtime.diagnostics().action_count == 1; }));
    runtime.request_manual_reset();
    ASSERT_TRUE(test::wait_until([&]() {
        const auto value = runtime.diagnostics();
        return value.scenario && value.scenario->snapshot->split_index == 1 &&
            !value.scenario->pending_action && !value.scenario->reset_pending;
    }));
    EXPECT_EQ(bridge->sync_count(), 2U);
    EXPECT_EQ(bridge->actions(), (std::vector{ActionOperation::split, ActionOperation::reset}));
    runtime.publish_frame(white_frame());
    ASSERT_TRUE(test::wait_until([&]() { return runtime.diagnostics().action_count == 3; }));
    runtime.stop();
    EXPECT_EQ(bridge->actions(), (std::vector{ActionOperation::split, ActionOperation::reset, ActionOperation::skip}));
}

TEST(InstanceRuntime, RejectedAutomaticResetReconcilesWithoutReusingItsFrame) {
    auto fake = std::make_unique<test::FakeBridgeClient>(test::make_snapshot(TimerPhase::running, 0, 2));
    auto* bridge = fake.get();
    bridge->on_execute = [bridge](ActionOperation operation) {
        if (operation == ActionOperation::reset) {
            bridge->set_snapshot(test::make_snapshot(TimerPhase::not_running, -1, 2));
            return BridgeControlResult{BridgeControlStatus::error, "already reset"};
        }
        return BridgeControlResult{BridgeControlStatus::ok, {}};
    };
    InstanceRuntime runtime{0, split_scenario(true), std::move(fake)};
    runtime.start();
    runtime.publish_frame(frame_with_gray(0));
    ASSERT_TRUE(test::wait_until([&]() {
        const auto value = runtime.diagnostics();
        return value.scenario && value.scenario->snapshot->phase == TimerPhase::not_running &&
            !value.scenario->reset_pending;
    }));
    EXPECT_EQ(bridge->sync_count(), 2U);
    EXPECT_EQ(bridge->actions(), std::vector{ActionOperation::reset});
    runtime.publish_frame(frame_with_gray(0));
    ASSERT_TRUE(test::wait_until([&]() { return runtime.diagnostics().action_count == 2; }));
    runtime.stop();
    EXPECT_EQ(bridge->actions(), (std::vector{ActionOperation::reset, ActionOperation::start}));
}

TEST(InstanceRuntime, FailedRejectedResetQuerySuspendsEvaluationUntilReconnect) {
    auto fake = std::make_unique<test::FakeBridgeClient>(test::make_snapshot(TimerPhase::running, 0, 2));
    auto* bridge = fake.get();
    std::atomic_bool fail_query{};
    bridge->on_synchronize = [bridge, &fail_query] {
        if (fail_query.load()) {
            bridge->set_ready(false);
            throw BridgeError(BridgeErrorKind::connection_lost, "rejected Reset Query failed");
        }
        return bridge->snapshot();
    };
    bridge->on_execute = [&fail_query](ActionOperation) {
        fail_query = true;
        return BridgeControlResult{BridgeControlStatus::error, "reset rejected"};
    };
    InstanceRuntime runtime{0, split_scenario(), std::move(fake)};
    runtime.start();
    ASSERT_TRUE(test::wait_until([&]() { return runtime.state() == InstanceState::ready; }));
    runtime.request_manual_reset();
    ASSERT_TRUE(test::wait_until([&]() { return runtime.state() == InstanceState::connecting; }));
    EXPECT_FALSE(runtime.diagnostics().scenario.has_value());
    pump(runtime, []() { return false; }, 50ms);
    EXPECT_EQ(bridge->actions(), std::vector{ActionOperation::reset});
    bridge->set_snapshot(test::make_snapshot(TimerPhase::running, 1, 2));
    fail_query = false;
    bridge->set_ready(true);
    ASSERT_TRUE(test::wait_until([&]() { return runtime.state() == InstanceState::ready; }));
    EXPECT_EQ(runtime.diagnostics().scenario->snapshot->split_index, 1);
    runtime.stop();
    EXPECT_EQ(bridge->actions(), std::vector{ActionOperation::reset});
}

TEST(InstanceRuntime, UnknownManualResetIsNotResentAfterResync) {
    auto fake = std::make_unique<test::FakeBridgeClient>(
        test::make_snapshot(TimerPhase::running, 0, 2)
    );
    auto* bridge = fake.get();
    bridge->on_execute = [](ActionOperation) {
        return BridgeControlResult{BridgeControlStatus::unknown, "unknown"};
    };
    Scenario scenario;
    scenario.start_condition = visible();
    InstanceRuntime runtime{0, std::move(scenario), std::move(fake)};
    runtime.start();
    ASSERT_TRUE(test::wait_until([&]() { return runtime.state() == InstanceState::ready; }));
    runtime.request_manual_reset();
    ASSERT_TRUE(test::wait_until([&]() { return runtime.diagnostics().generation >= 2; }));
    runtime.request_manual_reset();
    ASSERT_TRUE(test::wait_until([&]() {
        return runtime.diagnostics().last_action_result == "suppressed (unknown control outcome)";
    }));
    runtime.stop();
    EXPECT_EQ(bridge->actions(), std::vector{ActionOperation::reset});
}
