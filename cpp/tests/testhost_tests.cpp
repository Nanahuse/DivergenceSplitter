#include <gtest/gtest.h>

#include <chrono>
#include <cstdlib>
#include <functional>
#include <optional>
#include <string>
#include <filesystem>
#include <fstream>
#include <thread>
#include <opencv2/videoio.hpp>

#include "divergencesplitter/livesplit/adapter.hpp"
#include "divergencesplitter/livesplit/client.hpp"
#include "divergencesplitter/capture/configured_source.hpp"
#include "divergencesplitter/runtime/instance_runtime.hpp"
#include "divergencesplitter/runtime/session.hpp"

using namespace divergencesplitter;
using namespace std::chrono_literals;

namespace {

std::uint16_t testhost_port() {
    const char* value = std::getenv("DIVERGENCESPLITTER_TESTHOST_PORT");
    if (value == nullptr || *value == '\0') {
        return 0;
    }
    return static_cast<std::uint16_t>(std::stoi(value));
}

bool allow_control() {
    const char* value = std::getenv("DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL");
    return value != nullptr && std::string{value} == "1";
}

std::optional<BridgeEvent> wait_for_event(
    LiveSplitBridgeClient& client,
    const std::function<bool(const BridgeEvent&)>& predicate,
    std::chrono::milliseconds timeout = 3s
) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        if (auto event = client.next_event(100ms); event.has_value()) {
            if (!predicate || predicate(*event)) {
                return event;
            }
        }
    }
    return std::nullopt;
}

void drain_events(LiveSplitBridgeClient& client) {
    while (client.next_event(std::chrono::milliseconds{0}).has_value()) {
    }
}

}  // namespace

TEST(TestHost, QueryAndEvents) {
    const auto port = testhost_port();
    if (port == 0) {
        GTEST_SKIP() << "DIVERGENCESPLITTER_TESTHOST_PORT is not set";
    }
    LiveSplitClientOptions options;
    options.port = port;
    options.ready_timeout = 10s;
    LiveSplitBridgeClient client{options};
    client.wait_until_ready(10s);
    ASSERT_TRUE(client.is_ready());

    const auto snapshot = client.synchronize();
    EXPECT_GT(snapshot.session_id, 0U);
    EXPECT_GE(snapshot.split_count, 0);

    LiveSplitBridgeAdapter adapter{client};
    const auto update = adapter.attach();
    EXPECT_EQ(update.kind, UpdateKind::initial);
    EXPECT_EQ(update.snapshot.session_id, snapshot.session_id);

    drain_events(client);
}

TEST(TestHost, ControlPauseResumeEvents) {
    const auto port = testhost_port();
    if (port == 0) {
        GTEST_SKIP() << "DIVERGENCESPLITTER_TESTHOST_PORT is not set";
    }
    if (!allow_control()) {
        GTEST_SKIP() << "set DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1 to run controls";
    }
    LiveSplitClientOptions options;
    options.port = port;
    options.ready_timeout = 10s;
    LiveSplitBridgeClient client{options};
    client.wait_until_ready(10s);
    auto snapshot = client.synchronize();
    if (snapshot.phase == TimerPhase::not_running) {
        const auto start = client.execute(ActionOperation::start);
        ASSERT_EQ(start.status, BridgeControlStatus::ok) << start.message;
        snapshot = client.synchronize();
    }
    if (snapshot.phase != TimerPhase::running && snapshot.phase != TimerPhase::paused) {
        GTEST_SKIP() << "timer must be running or paused to verify events";
    }
    drain_events(client);

    const auto next_phase_event = [&](TimerPhase phase) {
        return wait_for_event(
            client,
            [phase](const BridgeEvent& value) {
                return value.kind == BridgeEventKind::timer &&
                       value.phase.has_value() && *value.phase == phase;
            }
        );
    };
    const auto check_event = [&](const BridgeEvent& event) {
        EXPECT_EQ(event.session_id, snapshot.session_id);
        EXPECT_TRUE(event.split_index.has_value());
    };

    if (snapshot.phase == TimerPhase::running) {
        const auto pause = client.execute(ActionOperation::pause);
        ASSERT_EQ(pause.status, BridgeControlStatus::ok) << pause.message;
        const auto paused = next_phase_event(TimerPhase::paused);
        ASSERT_TRUE(paused.has_value());
        check_event(*paused);
    }

    const auto resume = client.execute(ActionOperation::resume);
    ASSERT_EQ(resume.status, BridgeControlStatus::ok) << resume.message;
    const auto running = next_phase_event(TimerPhase::running);
    ASSERT_TRUE(running.has_value());
    check_event(*running);

    const auto pause = client.execute(ActionOperation::pause);
    ASSERT_EQ(pause.status, BridgeControlStatus::ok) << pause.message;
    const auto paused = next_phase_event(TimerPhase::paused);
    ASSERT_TRUE(paused.has_value());
    check_event(*paused);

    const auto resume_again = client.execute(ActionOperation::resume);
    ASSERT_EQ(resume_again.status, BridgeControlStatus::ok) << resume_again.message;
    const auto running_again = next_phase_event(TimerPhase::running);
    ASSERT_TRUE(running_again.has_value());
    check_event(*running_again);

    (void)client.execute(ActionOperation::reset);
}
TEST(TestHost, ControlPauseResume) {
    const auto port = testhost_port();
    if (port == 0) {
        GTEST_SKIP() << "DIVERGENCESPLITTER_TESTHOST_PORT is not set";
    }
    if (!allow_control()) {
        GTEST_SKIP() << "set DIVERGENCESPLITTER_TESTHOST_ALLOW_CONTROL=1 to run controls";
    }
    LiveSplitClientOptions options;
    options.port = port;
    options.ready_timeout = 10s;
    LiveSplitBridgeClient client{options};
    client.wait_until_ready(10s);
    auto before = client.synchronize();
    if (before.phase == TimerPhase::not_running) {
        const auto start = client.execute(ActionOperation::start);
        ASSERT_EQ(start.status, BridgeControlStatus::ok) << start.message;
        before = client.synchronize();
    }
    if (before.phase != TimerPhase::running && before.phase != TimerPhase::paused) {
        GTEST_SKIP() << "timer must be running or paused to verify pause/resume";
    }

    if (before.phase == TimerPhase::running) {
        const auto result = client.execute(ActionOperation::pause);
        ASSERT_EQ(result.status, BridgeControlStatus::ok) << result.message;
        EXPECT_EQ(client.synchronize().phase, TimerPhase::paused);
    }
    const auto result = client.execute(ActionOperation::resume);
    ASSERT_EQ(result.status, BridgeControlStatus::ok) << result.message;
    EXPECT_EQ(client.synchronize().phase, TimerPhase::running);

    (void)client.execute(ActionOperation::reset);
}

TEST(TestHost, RecordedVideoThroughYamlToRealBridgeControls) {
    const auto port = testhost_port();
    if (port == 0 || !allow_control()) GTEST_SKIP() << "TestHost control opt-in is not set";
    LiveSplitClientOptions options;
    options.port = port;
    LiveSplitBridgeClient observer{options};
    observer.wait_until_ready(10s);
    ASSERT_TRUE(observer.is_ready());
    ASSERT_EQ(observer.synchronize().split_count, 2) << "Requires the isolated two-segment TestHost run";
    ASSERT_TRUE(observer.execute(ActionOperation::reset).ok());
    const auto root = std::filesystem::temp_directory_path() /
        ("divergencesplitter-bridge-recorded-" + std::to_string(monotonic_now().nanoseconds));
    std::filesystem::create_directories(root);
    const auto cleanup = std::shared_ptr<void>{nullptr, [root](void*) {
        std::error_code error; std::filesystem::remove_all(root, error);
    }};
    const auto video = root / "input.avi";
    cv::VideoWriter writer(video.string(), cv::CAP_OPENCV_MJPEG,
        cv::VideoWriter::fourcc('M', 'J', 'P', 'G'), 30.0, {32, 32});
    ASSERT_TRUE(writer.isOpened());
    for (int gray : {10, 240, 10, 240, 10}) {
        for (int count = 0; count < 12; ++count)
            writer.write(cv::Mat(32, 32, CV_8UC3, cv::Scalar::all(gray)));
    }
    writer.release();
    const auto yaml = root / "scenario.yaml";
    {
        std::ofstream out(yaml);
        out << R"(start_condition: &edge
  type: then
  conditions:
    - type: not
      condition: {type: detected, minimum_score: 0.5, detector: {type: mean_brightness}}
    - {type: detected, minimum_score: 0.5, detector: {type: mean_brightness}}
splits:
  - rules:
      - {condition: *edge, action: split}
  - null
)";
    }
    const SourceConfiguration source = VideoSourceConfiguration{video.string(), {}};
    InstanceRuntime runtime{0, load_profile_scenario(yaml, source).scenario,
        std::make_unique<LiveSplitBridgeClient>(options)};
    runtime.start();
    const auto wait = [](const auto& predicate) {
        const auto deadline = std::chrono::steady_clock::now() + 10s;
        while (!predicate() && std::chrono::steady_clock::now() < deadline) std::this_thread::sleep_for(10ms);
        return predicate();
    };
    ASSERT_TRUE(wait([&] { return runtime.state() == InstanceState::ready; }));
    CapturePipeline capture(create_frame_source(source), create_frame_normalizer({}),
        [&](auto frame) { runtime.publish_frame(std::move(frame)); }, [](auto) {});
    capture.start();
    ASSERT_TRUE(wait([&] { return !capture.stats().running; }));
    capture.stop();
    ASSERT_TRUE(wait([&] {
        const auto value = runtime.diagnostics();
        return value.scenario && value.scenario->snapshot && value.scenario->snapshot->split_index == 1 &&
            !value.scenario->pending_action;
    }));
    const auto diagnostics = runtime.diagnostics();
    EXPECT_EQ(diagnostics.action_count, 2U);
    EXPECT_EQ(diagnostics.last_action, ActionOperation::split);
    EXPECT_EQ(diagnostics.last_action_result, "ok");
    EXPECT_EQ(observer.synchronize().split_index, 1);
    EXPECT_EQ(capture.stats().last_error, "reached the end of the video file");
    runtime.stop();
    EXPECT_TRUE(observer.execute(ActionOperation::reset).ok());
}
