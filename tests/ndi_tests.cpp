#include <gtest/gtest.h>

#include <atomic>
#include <condition_variable>
#include <future>
#include <mutex>
#include <thread>

#include "divergencesplitter/capture/ndi.hpp"
#include "divergencesplitter/capture/frame_source.hpp"
#include "divergencesplitter/capture/capture_pipeline.hpp"

using namespace divergencesplitter;
using namespace std::chrono_literals;

namespace {
struct FakeApi final : NdiApi {
    int initialized{}, destroyed{}, finders{}, freed_finders{}, receivers{}, freed_receivers{}, freed_frames{};
    bool init_ok{true}, finder_ok{true}, receiver_ok{true}, fail_sources{};
    std::vector<std::string> names{"PC (B)", "PC (A)", "PC (A)"};
    std::string selected;
    NdiFrameType next_type{NdiFrameType::none};
    NdiPixelFormat next_format{NdiPixelFormat::bgra};
    std::vector<std::uint8_t> pixels{1, 2, 3, 255, 4, 5, 6, 255};
    std::uint32_t last_timeout{};
    bool initialize() override { ++initialized; return init_ok; }
    void destroy() noexcept override { ++destroyed; }
    std::string version() const override { return "fake"; }
    Handle create_finder() override { ++finders; return finder_ok ? this : nullptr; }
    void destroy_finder(Handle) noexcept override { ++freed_finders; }
    void wait_for_sources(Handle, std::uint32_t ms) override { std::this_thread::sleep_for(std::chrono::milliseconds{ms}); }
    std::vector<std::string> sources(Handle) override {
        if (fail_sources) throw std::runtime_error("discovery failed");
        return names;
    }
    Handle create_receiver(const std::string& name) override {
        ++receivers; selected = name; return receiver_ok ? this : nullptr;
    }
    void destroy_receiver(Handle) noexcept override { ++freed_receivers; }
    NdiCapturedFrame capture(Handle, std::uint32_t timeout) override {
        last_timeout = timeout;
        return {next_type, {2, 1, 8, next_format, pixels.data()},
            std::shared_ptr<void>(this, [this](void*) { ++freed_frames; })};
    }
};
}

TEST(Ndi, SharedRuntimeOutlivesFindersAndReceivers) {
    auto api = std::make_shared<FakeApi>();
    {
        auto runtime = std::make_shared<NdiRuntime>(api);
        EXPECT_EQ(api->initialized, 1);
        auto source = std::make_unique<NdiFrameSource>(NdiSourceOptions{"saved offline source"}, runtime);
        source->open();
        EXPECT_EQ(api->selected, "saved offline source");
        EXPECT_EQ(discover_ndi_sources(0ms, runtime), (std::vector<std::string>{"PC (A)", "PC (B)"}));
        EXPECT_EQ(api->freed_finders, 1);
        runtime.reset();
        EXPECT_EQ(api->destroyed, 0);
        source.reset();
        EXPECT_EQ(api->freed_receivers, 1);
    }
    EXPECT_EQ(api->destroyed, 1);
}

TEST(Ndi, FailedInitializationDoesNotDestroyAnUninitializedSdk) {
    auto api = std::make_shared<FakeApi>();
    api->init_ok = false;
    EXPECT_THROW((void)std::make_shared<NdiRuntime>(api), FrameSourceError);
    EXPECT_EQ(api->initialized, 1);
    EXPECT_EQ(api->destroyed, 0);
}

TEST(Ndi, DiscoveryCopiesNamesAndCleansUpOnExceptions) {
    auto api = std::make_shared<FakeApi>();
    auto runtime = std::make_shared<NdiRuntime>(api);
    auto names = discover_ndi_sources(0ms, runtime);
    api->names = {"new source"};
    EXPECT_EQ(names.front(), "PC (A)");
    EXPECT_EQ(discover_ndi_sources(0ms, runtime), api->names);
    api->fail_sources = true;
    EXPECT_THROW((void)discover_ndi_sources(0ms, runtime), std::runtime_error);
    EXPECT_EQ(api->finders, 3);
    EXPECT_EQ(api->freed_finders, 3);
    api->finder_ok = false;
    EXPECT_THROW((void)discover_ndi_sources(0ms, runtime), FrameSourceError);
    EXPECT_EQ(api->freed_finders, 3);
}

TEST(Ndi, ReceiverCreationFailureAndIdempotentClose) {
    auto api = std::make_shared<FakeApi>();
    auto runtime = std::make_shared<NdiRuntime>(api);
    NdiFrameSource source{{"sender"}, runtime};
    api->receiver_ok = false;
    EXPECT_THROW(source.open(), FrameSourceError);
    EXPECT_EQ(api->freed_receivers, 0);
    api->receiver_ok = true;
    source.open();
    source.open();
    source.close();
    source.close();
    EXPECT_EQ(api->receivers, 2);
    EXPECT_EQ(api->freed_receivers, 1);
}

TEST(Ndi, TimeoutAndSenderReturnKeepTheSameReceiver) {
    auto api = std::make_shared<FakeApi>();
    NdiFrameSource source{{"sender"}, std::make_shared<NdiRuntime>(api)};
    source.open();
    MonotonicTime captured_at;
    for (int i = 0; i < 10; ++i) EXPECT_TRUE(source.read(captured_at).empty());
    api->next_type = NdiFrameType::video;
    const auto image = source.read(captured_at);
    EXPECT_EQ(image.at<cv::Vec3b>(0, 0), (cv::Vec3b{1, 2, 3}));
    std::fill(api->pixels.begin(), api->pixels.end(), 0);
    EXPECT_EQ(image.at<cv::Vec3b>(0, 0), (cv::Vec3b{1, 2, 3}));
    EXPECT_EQ(api->receivers, 1);
    EXPECT_LE(api->last_timeout, 50u);
    EXPECT_EQ(api->freed_frames, 11);
}

TEST(Ndi, AllNonVideoBuffersAndConversionFailuresAreReleased) {
    auto api = std::make_shared<FakeApi>();
    NdiFrameSource source{{"sender"}, std::make_shared<NdiRuntime>(api)};
    source.open();
    MonotonicTime captured_at;
    for (auto type : {NdiFrameType::audio, NdiFrameType::metadata, NdiFrameType::status_change}) {
        api->next_type = type;
        EXPECT_TRUE(source.read(captured_at).empty());
    }
    api->next_type = NdiFrameType::video;
    api->next_format = NdiPixelFormat::unsupported;
    EXPECT_THROW((void)source.read(captured_at), FrameSourceError);
    api->next_type = NdiFrameType::error;
    EXPECT_THROW((void)source.read(captured_at), FrameSourceError);
    EXPECT_EQ(api->freed_frames, 5);
}

TEST(Ndi, RgbFormatsHonorPaddedStrideAndOwnTheirData) {
    std::vector<std::uint8_t> data{10, 20, 30, 0, 99, 99, 99, 99, 40, 50, 60, 255, 99, 99, 99, 99};
    for (auto format : {NdiPixelFormat::bgra, NdiPixelFormat::bgrx, NdiPixelFormat::rgba, NdiPixelFormat::rgbx}) {
        const auto output = ndi_video_to_bgr({1, 2, 8, format, data.data()});
        const bool blue = format == NdiPixelFormat::bgra || format == NdiPixelFormat::bgrx;
        EXPECT_EQ(output.at<cv::Vec3b>(1, 0), blue ? (cv::Vec3b{40, 50, 60}) : (cv::Vec3b{60, 50, 40}));
    }
    auto output = ndi_video_to_bgr({1, 2, 8, NdiPixelFormat::bgra, data.data()});
    std::fill(data.begin(), data.end(), 0);
    EXPECT_EQ(output.at<cv::Vec3b>(0, 0), (cv::Vec3b{10, 20, 30}));
}

TEST(Ndi, UyvyAndUyvaHonorStrideAndIgnoreAlphaPlane) {
    std::vector<std::uint8_t> data{128, 16, 128, 235, 99, 99, 128, 235, 128, 16, 99, 99, 0, 0, 0, 0};
    for (auto format : {NdiPixelFormat::uyvy, NdiPixelFormat::uyva}) {
        const auto output = ndi_video_to_bgr({2, 2, 6, format, data.data()});
        EXPECT_EQ(output.at<cv::Vec3b>(0, 0), (cv::Vec3b{0, 0, 0}));
        EXPECT_EQ(output.at<cv::Vec3b>(1, 0), (cv::Vec3b{255, 255, 255}));
    }
}

TEST(Ndi, RejectsInvalidDimensionsFormatsAndStride) {
    std::uint8_t data[8]{};
    EXPECT_THROW((void)ndi_video_to_bgr({2, 1, 7, NdiPixelFormat::bgra, data}), FrameSourceError);
    EXPECT_THROW((void)ndi_video_to_bgr({1, 1, 4, NdiPixelFormat::uyvy, data}), FrameSourceError);
    EXPECT_THROW((void)ndi_video_to_bgr({2, 0, 8, NdiPixelFormat::bgra, data}), FrameSourceError);
    EXPECT_THROW((void)ndi_video_to_bgr({2, 1, 8, NdiPixelFormat::bgra, nullptr}), FrameSourceError);
    EXPECT_THROW((void)ndi_video_to_bgr({2, 1, -8, NdiPixelFormat::bgra, data}), FrameSourceError);
}

namespace {
struct PipelineState {
    std::atomic_int opened{}, closed{}, reads{};
    std::mutex mutex;
    std::condition_variable changed;
    bool resume{}, fatal{};
};
class ControlledSource final : public FrameSource {
public:
    explicit ControlledSource(std::shared_ptr<PipelineState> state) : state_(std::move(state)) {}
    void open() override { ++state_->opened; }
    cv::Mat read(MonotonicTime& captured_at) override {
        std::unique_lock lock{state_->mutex};
        state_->changed.wait_for(lock, 20ms, [this] { return state_->resume || state_->fatal; });
        ++state_->reads;
        state_->changed.notify_all();
        if (state_->fatal) throw FrameSourceError("fatal receiver failure", false);
        if (!state_->resume) return {};
        state_->resume = false;
        captured_at = monotonic_now();
        return cv::Mat(2, 2, CV_8UC3, cv::Scalar{10, 20, 30});
    }
    void close() noexcept override { ++state_->closed; }
    std::string describe() const override { return "controlled"; }
private:
    std::shared_ptr<PipelineState> state_;
};
}

TEST(CapturePipeline, TimeoutResumeAndPromptStopWithoutReopen) {
    auto state = std::make_shared<PipelineState>();
    std::promise<void> delivered;
    auto received = delivered.get_future();
    CapturePipeline pipeline{std::make_unique<ControlledSource>(state), FrameNormalizer{},
        [&](auto) { delivered.set_value(); }, [](auto error) { ADD_FAILURE() << error; }};
    pipeline.start();
    {
        std::unique_lock lock{state->mutex};
        ASSERT_TRUE(state->changed.wait_for(lock, 2s, [&] { return state->reads >= 3; }));
        state->resume = true;
    }
    state->changed.notify_all();
    EXPECT_EQ(received.wait_for(2s), std::future_status::ready);
    const auto start = std::chrono::steady_clock::now();
    pipeline.stop();
    EXPECT_LT(std::chrono::steady_clock::now() - start, 500ms);
    EXPECT_EQ(state->opened, 1);
    EXPECT_EQ(state->closed, 1);
    EXPECT_EQ(pipeline.stats().frames_published, 1u);
}

TEST(CapturePipeline, FatalErrorIsReportedAndStopsCapture) {
    auto state = std::make_shared<PipelineState>();
    state->fatal = true;
    std::promise<std::string> reported;
    auto error = reported.get_future();
    CapturePipeline pipeline{std::make_unique<ControlledSource>(state), FrameNormalizer{},
        [](auto) { ADD_FAILURE(); }, [&](auto message) { reported.set_value(message); }};
    pipeline.start();
    ASSERT_EQ(error.wait_for(2s), std::future_status::ready);
    EXPECT_EQ(error.get(), "fatal receiver failure");
    pipeline.stop();
    EXPECT_FALSE(pipeline.stats().running);
    EXPECT_GE(state->closed, 1);
}
