#include <windows.h>
#include <Processing.NDI.Lib.h>
#include <Processing.NDI.DynamicLoad.h>
#include <gtest/gtest.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <mutex>
#include <thread>
#include <iostream>

#include "divergencesplitter/capture/capture_pipeline.hpp"
#include "divergencesplitter/capture/ndi.hpp"
#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
#include "divergencesplitter/runtime/scenario_runtime.hpp"

using namespace divergencesplitter;
using namespace std::chrono_literals;

namespace {
// An actual SDK sender, excluded from the product ZIP. Network reception and
// reconnection are tested with the real DLL, independently of the fake API tests.
class Sender {
public:
    explicit Sender(const NDIlib_v5* api) : api_(api) {
        NDIlib_send_create_t settings;
        settings.p_ndi_name = "DivergenceSplitter integration test";
        sender_ = api_->send_create(&settings);
        if (!sender_) throw std::runtime_error("cannot create SDK test sender");
        name = api_->send_get_source_name(sender_)->p_ndi_name;
        thread_ = std::jthread([this](std::stop_token stop) {
            cv::Mat image(48, 64, CV_8UC4, cv::Scalar{230, 230, 230, 255});
            NDIlib_video_frame_v2_t frame;
            frame.xres = image.cols;
            frame.yres = image.rows;
            frame.FourCC = NDIlib_FourCC_video_type_BGRX;
            frame.frame_rate_N = 30;
            frame.frame_rate_D = 1;
            frame.frame_format_type = NDIlib_frame_format_type_progressive;
            frame.p_data = image.data;
            frame.line_stride_in_bytes = static_cast<int>(image.step);
            while (!stop.stop_requested()) api_->send_send_video_v2(sender_, &frame);
        });
    }
    ~Sender() {
        thread_.request_stop();
        thread_.join();
        api_->send_destroy(sender_);
    }
    std::string name;
private:
    const NDIlib_v5* api_;
    NDIlib_send_instance_t sender_{};
    std::jthread thread_;
};

template<class Predicate>
bool wait_until(Predicate predicate, std::chrono::seconds timeout = 20s) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        if (predicate()) return true;
        std::this_thread::sleep_for(50ms);
    }
    return false;
}
}

TEST(NdiSdkLoopback, DiscoversReceivesNormalizesEvaluatesAndReconnects) {
    auto runtime = acquire_ndi_runtime();
    auto module = GetModuleHandleW(L"Processing.NDI.Lib.x64.dll");
    ASSERT_NE(module, nullptr);
    auto load = reinterpret_cast<const NDIlib_v5* (*)()>(GetProcAddress(module, "NDIlib_v5_load"));
    ASSERT_NE(load, nullptr);
    const auto* api = load();
    auto sender = std::make_unique<Sender>(api);
    const auto name = sender->name;
    ASSERT_TRUE(wait_until([&] {
        auto names = discover_ndi_sources(250ms, runtime);
        return std::find(names.begin(), names.end(), name) != names.end();
    }));

    Scenario scenario;
    scenario.start_condition = std::make_shared<DetectedCondition>(
        std::make_shared<MeanBrightnessDetector>(), 0.5);
    ScenarioRuntime scenario_runtime{scenario};
    LiveSplitUpdate initial;
    initial.kind = UpdateKind::initial;
    initial.snapshot = {1, 1, 1, TimerPhase::not_running, -1, 0};
    scenario_runtime.apply_update(initial);
    std::atomic_int received{}, actions{};
    std::mutex mutex;
    std::string failure;
    CapturePipeline pipeline{
        std::make_unique<NdiFrameSource>(NdiSourceOptions{name}, runtime),
        FrameNormalizer{CropMargins{2, 2, 2, 2}, OutputSize{32, 24}},
        [&](auto frame) {
            ++received;
            FrameContext context{frame};
            const auto action = scenario_runtime.evaluate(context);
            if (action && action->operation == ActionOperation::start) ++actions;
        },
        [&](auto error) { std::scoped_lock lock{mutex}; failure = error; }
    };
    pipeline.start();
    ASSERT_TRUE(wait_until([&] { return received.load() >= 10 && actions.load() == 1; }));
    auto preview = pipeline.latest_preview();
    ASSERT_NE(preview, nullptr);
    EXPECT_EQ(preview->size(), (cv::Size{32, 24}));
    EXPECT_EQ(preview->type(), CV_8UC3);
    EXPECT_GT(cv::mean(*preview)[0], 200);

    sender.reset();
    // Give queued frames time to drain, then verify capture remains alive while
    // the sender is absent. The same receiver is kept by CapturePipeline.
    std::this_thread::sleep_for(2s);
    const auto before_resume = received.load();
    EXPECT_TRUE(pipeline.stats().running);
    sender = std::make_unique<Sender>(api);
    EXPECT_EQ(sender->name, name);
    ASSERT_TRUE(wait_until([&] { return received.load() >= before_resume + 10; }));

    // Set NDI_SOAK_SECONDS for a longer local stability run; the default remains
    // short enough for CI. No initialization-only test is treated as reception.
    const char* soak = std::getenv("NDI_SOAK_SECONDS");
    const int seconds = soak ? std::clamp(std::atoi(soak), 0, 3600) : 2;
    const auto start = received.load();
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds{seconds};
    auto last_progress = std::chrono::steady_clock::now();
    int last_count = start;
    while (std::chrono::steady_clock::now() < deadline) {
        std::this_thread::sleep_for(200ms);
        ASSERT_TRUE(pipeline.stats().running);
        if (std::chrono::steady_clock::now() - last_progress >= 5s) {
            EXPECT_GT(received.load(), last_count) << "NDI reception stalled during the stability run";
            last_count = received.load();
            last_progress = std::chrono::steady_clock::now();
        }
    }
    if (seconds > 0) EXPECT_GT(received.load(), start);
    const auto stopping = std::chrono::steady_clock::now();
    pipeline.stop();
    EXPECT_LT(std::chrono::steady_clock::now() - stopping, 500ms);
    std::scoped_lock lock{mutex};
    EXPECT_TRUE(failure.empty()) << failure;
    std::cout << "NDI reception evidence: runtime=" << runtime->api().version()
              << ", soak_seconds=" << seconds << ", frames=" << received.load()
              << ", actions=" << actions.load() << ", error=" << failure << std::endl;
}
