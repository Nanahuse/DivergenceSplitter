#include <gtest/gtest.h>

#include <chrono>
#include <functional>
#include <memory>
#include <thread>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
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
    return std::make_shared<SharedFrameEvaluation>(
        SharedFrameEvaluation{
            Frame{test::solid(4, 4, gray), MonotonicTime{0}},
            MonotonicTime{0},
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
    scenario.start_condition = visible();
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
