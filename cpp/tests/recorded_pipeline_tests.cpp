#include <gtest/gtest.h>
#include <opencv2/videoio.hpp>
#include <filesystem>
#include <fstream>
#include <atomic>
#include <mutex>
#include <sstream>

#include "divergencesplitter/capture/configured_source.hpp"
#include "divergencesplitter/runtime/instance_runtime.hpp"
#include "divergencesplitter/runtime/session.hpp"
#include "test_support.hpp"

using namespace divergencesplitter;
using namespace std::chrono_literals;

namespace {
// Keep source I/O separate from the frame sink's evaluation/confirmation wait.
// In particular, Stop must join an in-flight backend open/read before returning.
class TracedSource final : public FrameSource {
public:
    explicit TracedSource(std::unique_ptr<FrameSource> source) : source_(std::move(source)) {}
    void open() override {
        stage = "opening source";
        source_->open();
        { std::scoped_lock lock{mutex_}; backend_ = source_->opened_format().backend; }
        stage = "source opened";
    }
    cv::Mat read(MonotonicTime& at) override {
        stage = "reading source";
        auto image = source_->read(at);
        stage = image.empty() ? "no source frame" : "frame decoded";
        return image;
    }
    void close() noexcept override { stage = "closing source"; source_->close(); stage = "source closed"; }
    std::string describe() const override { return source_->describe(); }
    std::string backend() const { std::scoped_lock lock{mutex_}; return backend_; }
    std::atomic<const char*> stage{"not started"};
private:
    std::unique_ptr<FrameSource> source_;
    mutable std::mutex mutex_;
    std::string backend_;
};

std::string runtime_trace(const InstanceRuntime& runtime, const test::FakeBridgeClient& bridge) {
    const auto value = runtime.diagnostics();
    std::ostringstream out;
    out << "instance=" << to_string(value.state) << " error=" << value.error
        << " actions=";
    for (auto action : bridge.actions()) out << to_string(action) << ',';
    out << " result=" << value.last_action_result << " queries=" << bridge.sync_count();
    if (value.scenario) {
        const auto& scenario = *value.scenario;
        out << " evaluations=" << scenario.evaluation_count
            << " pending=" << (scenario.pending_action ? to_string(*scenario.pending_action) : "none")
            << " reset_pending=" << (scenario.reset_pending ? to_string(*scenario.reset_pending) : "none")
            << " rule_errors=" << scenario.rule_errors;
        if (scenario.snapshot) out << " phase=" << to_string(scenario.snapshot->phase)
                                   << " split=" << scenario.snapshot->split_index;
    }
    return out.str();
}

class CaptureTrace {
public:
    void error(const std::string& message) { std::scoped_lock lock{mutex_}; errors_ += message + '\n'; }
    std::string describe(const CapturePipeline& capture, const TracedSource& source) const {
        const auto stats = capture.stats();
        std::scoped_lock lock{mutex_};
        std::ostringstream out;
        out << "source=" << source.stage.load() << " backend=" << source.backend()
            << " captured=" << stats.frames_captured
            << " published=" << stats.frames_published << " running=" << stats.running
            << " last_error=" << stats.last_error << " errors=" << errors_;
        return out.str();
    }
private:
    mutable std::mutex mutex_;
    std::string errors_;
};

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
void publish_and_settle(InstanceRuntime& runtime, const test::FakeBridgeClient& bridge,
                        const std::shared_ptr<SharedFrameEvaluation>& frame) {
    const auto before = runtime.diagnostics().scenario->evaluation_count;
    runtime.publish_frame(frame);
    if (!test::wait_until([&] {
        const auto value = runtime.diagnostics();
        return value.scenario && value.scenario->evaluation_count > before &&
            !value.scenario->pending_action && !value.scenario->reset_pending;
    }, 2s)) throw std::runtime_error("recorded frame evaluation/control did not settle: " +
                                    runtime_trace(runtime, bridge));
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
    CaptureTrace trace;
    auto source = std::make_unique<TracedSource>(create_frame_source(profile.source));
    auto* traced_source = source.get();
    CapturePipeline capture(std::move(source),
        create_frame_normalizer(std::get<VideoSourceConfiguration>(profile.source).transform),
        [&](auto frame) {
            traced_source->stage = "waiting for evaluation/control";
            if (frame->frame.image.size() != cv::Size{4, 4}) normalized = false;
            if (++frames == 17) {
                traced_source->stage = "waiting for Undo";
                auto state = bridge->snapshot();
                state.split_index = 0;  // External Undo after the first Split.
                bridge->set_snapshot(state);
                bridge->push_event({BridgeEventKind::timer, 1, TimerPhase::running, 0});
                if (!test::wait_until([&] { return runtime.diagnostics().scenario->snapshot->split_index == 0; }))
                    throw std::runtime_error("Undo was not observed: " + runtime_trace(runtime, *bridge));
                traced_source->stage = "waiting for evaluation/control";
            }
            publish_and_settle(runtime, *bridge, frame);
            traced_source->stage = "frame settled";
        }, [&](const auto& error) { trace.error(error); });
    capture.start();
    const bool completed = test::wait_until([&] { return !capture.stats().running; }, 5s);
    EXPECT_TRUE(completed) << "frames=" << frames.load() << ' ' << trace.describe(capture, *traced_source)
                           << '\n' << runtime_trace(runtime, *bridge);
    capture.stop();
    EXPECT_EQ(capture.stats().last_error, "reached the end of the video file")
        << trace.describe(capture, *traced_source) << '\n' << runtime_trace(runtime, *bridge);
    runtime.stop();
    EXPECT_EQ(frames.load(), 28);
    EXPECT_TRUE(normalized.load());
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
    CaptureTrace trace;
    auto traced = std::make_unique<TracedSource>(create_frame_source(source));
    auto* traced_source = traced.get();
    CapturePipeline capture(std::move(traced), create_frame_normalizer({}), [&](auto frame) {
        traced_source->stage = "waiting for first instance";
        publish_and_settle(one, *first_bridge, frame);
        traced_source->stage = "waiting for second instance";
        publish_and_settle(two, *second_bridge, frame);
        traced_source->stage = "frame settled";
    }, [&](const auto& error) { trace.error(error); });
    capture.start();
    EXPECT_TRUE(test::wait_until([&] { return !capture.stats().running; }, 5s))
        << trace.describe(capture, *traced_source) << '\n' << runtime_trace(one, *first_bridge)
        << '\n' << runtime_trace(two, *second_bridge);
    capture.stop();
    EXPECT_EQ(capture.stats().last_error, "reached the end of the video file")
        << trace.describe(capture, *traced_source) << '\n' << runtime_trace(one, *first_bridge)
        << '\n' << runtime_trace(two, *second_bridge);
    one.stop(); two.stop();
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

TEST(VideoFileSource, MjpegUsesBuiltinDecoderBeforePlatformBackends) {
    Recording recording;
    recording.write({10, 240});
    VideoFileFrameSource source{{(recording.root / "input.avi").string()}};
    source.open();
    const auto format = source.opened_format();
    EXPECT_EQ(format.backend, "CV_MJPEG");
    EXPECT_EQ(format.width, 32);
    EXPECT_EQ(format.height, 32);
    EXPECT_DOUBLE_EQ(format.fps, 40.0);
    MonotonicTime at;
    EXPECT_FALSE(source.read(at).empty());
    source.close();
    EXPECT_TRUE(source.opened_format().backend.empty());
}

TEST(VideoFileSource, NonMjpegInputFallsBackToOtherBackends) {
#ifndef _WIN32
    GTEST_SKIP() << "H.264 fallback requires the Windows Media Foundation build";
#endif
    const auto video = std::filesystem::path{__FILE__}.parent_path() / "data" / "fallback-h264.mp4";
    VideoFileFrameSource source{{video.string()}};
    source.open();
    EXPECT_NE(source.opened_format().backend, "CV_MJPEG");
    MonotonicTime at;
    const auto decoded = source.read(at);
    ASSERT_FALSE(decoded.empty());
    EXPECT_EQ(decoded.size(), (cv::Size{128, 128}));
    EXPECT_NEAR(cv::mean(decoded)[0], 128.0, 3.0);
}
