#include <gtest/gtest.h>
#include <opencv2/videoio.hpp>
#include <filesystem>
#include <fstream>
#include <atomic>

#include "divergencesplitter/capture/configured_source.hpp"
#include "divergencesplitter/runtime/instance_runtime.hpp"
#include "divergencesplitter/runtime/session.hpp"
#include "test_support.hpp"

using namespace divergencesplitter;
using namespace std::chrono_literals;

namespace {
class Recording {
public:
    Recording() {
        root = std::filesystem::temp_directory_path() /
            ("divergencesplitter-recorded-" + std::to_string(monotonic_now().nanoseconds));
        std::filesystem::create_directories(root);
    }
    ~Recording() { std::error_code error; std::filesystem::remove_all(root, error); }

    void write(const std::vector<int>& segments, bool bright_border = false, double fps = 40.0) const {
        cv::VideoWriter writer((root / "input.avi").string(), cv::CAP_OPENCV_MJPEG,
            cv::VideoWriter::fourcc('M', 'J', 'P', 'G'), fps, {32, 32});
        ASSERT_TRUE(writer.isOpened()) << "MJPEG recording encoder unavailable";
        for (int gray : segments) {
            cv::Mat image(32, 32, CV_8UC3, cv::Scalar::all(gray));
            if (bright_border) image.colRange(8, 32).setTo(cv::Scalar::all(255));
            for (int frame = 0; frame < 4; ++frame) writer.write(image);
        }
    }

    std::filesystem::path scenario(bool splits = true) const {
        const auto path = root / (splits ? "split.yaml" : "start.yaml");
        std::ofstream out(path);
        out << R"(start_condition:
  type: then
  conditions:
    - type: not
      condition: {type: detected, minimum_score: 0.5, detector: {type: mean_brightness}}
    - {type: detected, minimum_score: 0.5, detector: {type: mean_brightness}}
)";
        if (splits) out << R"(splits:
  - rules:
      - action: split
        condition:
          type: then
          conditions:
            - type: not
              condition: {type: detected, minimum_score: 0.5, detector: {type: mean_brightness}}
            - {type: detected, minimum_score: 0.5, detector: {type: mean_brightness}}
  - null
)";
        else out << "splits: []\n";
        return path;
    }
    std::filesystem::path root;
};

void follow_controls(test::FakeBridgeClient* bridge) {
    bridge->on_execute = [bridge](ActionOperation action) {
        auto state = bridge->snapshot();
        if (action == ActionOperation::start) { state.phase = TimerPhase::running; state.split_index = 0; }
        else if (action == ActionOperation::split) ++state.split_index;
        else if (action == ActionOperation::pause) state.phase = TimerPhase::paused;
        else if (action == ActionOperation::resume) state.phase = TimerPhase::running;
        else if (action == ActionOperation::reset) { state.phase = TimerPhase::not_running; state.split_index = -1; }
        bridge->set_snapshot(state);
        bridge->push_event(BridgeEvent{action == ActionOperation::reset ? BridgeEventKind::reset : BridgeEventKind::timer,
            state.session_id, state.phase, state.split_index});
        return BridgeControlResult{BridgeControlStatus::ok, {}};
    };
}

// Frame barriers compare input order and operation history, not wall-clock
// scheduling. Decoding, normalization, evaluation, and control still use the
// production VideoFileFrameSource / CapturePipeline / InstanceRuntime threads.
void publish_and_settle(InstanceRuntime& runtime, const std::shared_ptr<SharedFrameEvaluation>& frame) {
    const auto before = runtime.diagnostics().scenario->evaluation_count;
    runtime.publish_frame(frame);
    if (!test::wait_until([&] {
        const auto value = runtime.diagnostics();
        return value.scenario && value.scenario->evaluation_count > before &&
            !value.scenario->pending_action && !value.scenario->reset_pending;
    }, 2s)) throw std::runtime_error("recorded frame evaluation/control did not settle");
}
}

TEST(RecordedPipeline, ProfileYamlDecodeTransformStartSplitUndoAndReentry) {
    Recording recording;
    recording.write({10, 240, 10, 240, 10, 240, 10}, true);
    Profile profile;
    profile.source = VideoSourceConfiguration{(recording.root / "input.avi").string(),
        {CropConfiguration{0, 24, 0, 0}, ResizeConfiguration{4, 4}}};
    profile.instances.push_back({{54000}, recording.scenario().string()});
    const auto profile_path = recording.root / "profile.json";
    save_profile(profile_path, profile);
    profile = load_profile(profile_path).profile;
    auto loaded = load_profile_scenario(profile.instances[0].scenario, profile.source);
    auto fake = std::make_unique<test::FakeBridgeClient>(test::make_snapshot(TimerPhase::not_running, -1, 2));
    auto* bridge = fake.get();
    follow_controls(bridge);
    InstanceRuntime runtime{0, std::move(loaded.scenario), std::move(fake)};
    runtime.start();
    ASSERT_TRUE(test::wait_until([&] { return runtime.state() == InstanceState::ready; }));
    std::atomic_int frames{};
    std::atomic_bool normalized{true};
    CapturePipeline capture(create_frame_source(profile.source),
        create_frame_normalizer(std::get<VideoSourceConfiguration>(profile.source).transform),
        [&](auto frame) {
            if (frame->frame.image.size() != cv::Size{4, 4}) normalized = false;
            if (++frames == 17) {
                auto state = bridge->snapshot();
                state.split_index = 0;  // External Undo after the first Split.
                bridge->set_snapshot(state);
                bridge->push_event({BridgeEventKind::timer, 1, TimerPhase::running, 0});
                if (!test::wait_until([&] { return runtime.diagnostics().scenario->snapshot->split_index == 0; }))
                    throw std::runtime_error("Undo was not observed");
            }
            publish_and_settle(runtime, frame);
        }, [](auto) {});
    capture.start();
    ASSERT_TRUE(test::wait_until([&] { return !capture.stats().running; }, 5s));
    capture.stop();
    runtime.stop();
    EXPECT_EQ(frames.load(), 28);
    EXPECT_TRUE(normalized.load());
    EXPECT_EQ(capture.stats().last_error, "reached the end of the video file");
    EXPECT_EQ(bridge->actions(), (std::vector{ActionOperation::start, ActionOperation::split, ActionOperation::split}));
}

TEST(RecordedPipeline, MultipleYamlScenariosRemainIndependentOnSharedFrames) {
    Recording recording;
    recording.write({10, 240, 10, 240, 10});
    const SourceConfiguration source = VideoSourceConfiguration{(recording.root / "input.avi").string(), {}};
    auto first = std::make_unique<test::FakeBridgeClient>(test::make_snapshot(TimerPhase::not_running, -1, 2));
    auto second = std::make_unique<test::FakeBridgeClient>(test::make_snapshot(TimerPhase::not_running, -1, 2));
    auto* first_bridge = first.get();
    auto* second_bridge = second.get();
    follow_controls(first_bridge);
    follow_controls(second_bridge);
    InstanceRuntime one{0, load_profile_scenario(recording.scenario(), source).scenario, std::move(first)};
    InstanceRuntime two{1, load_profile_scenario(recording.scenario(false), source).scenario, std::move(second)};
    one.start(); two.start();
    ASSERT_TRUE(test::wait_until([&] { return one.state() == InstanceState::ready && two.state() == InstanceState::ready; }));
    CapturePipeline capture(create_frame_source(source), create_frame_normalizer({}), [&](auto frame) {
        publish_and_settle(one, frame);
        publish_and_settle(two, frame);
    }, [](auto) {});
    capture.start();
    ASSERT_TRUE(test::wait_until([&] { return !capture.stats().running; }, 5s));
    capture.stop(); one.stop(); two.stop();
    EXPECT_EQ(capture.stats().last_error, "reached the end of the video file");
    EXPECT_EQ(first_bridge->actions(), (std::vector{ActionOperation::start, ActionOperation::split}));
    EXPECT_EQ(second_bridge->actions(), std::vector{ActionOperation::start});
}

TEST(RecordedPipeline, LowFpsPlaybackStopsBeforeTheNextFrameIsDue) {
    Recording recording;
    recording.write({10, 240}, false, 1.0);  // MJPEG's minimum: one second between frames.
    std::atomic_int frames{};
    CapturePipeline capture(std::make_unique<VideoFileFrameSource>(
        VideoFileSourceOptions{(recording.root / "input.avi").string()}), create_frame_normalizer({}),
        [&](auto) { ++frames; }, [](auto) {});
    capture.start();
    ASSERT_TRUE(test::wait_until([&] { return frames.load() > 0; }));
    const auto started = std::chrono::steady_clock::now();
    capture.stop();
    EXPECT_LT(std::chrono::steady_clock::now() - started, 500ms);
    EXPECT_FALSE(capture.stats().running);
}
