#pragma once

#include <opencv2/core.hpp>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

#include "divergencesplitter/capture/frame_source.hpp"
#include "divergencesplitter/capture/normalizer.hpp"
#include "divergencesplitter/clock.hpp"
#include "divergencesplitter/frame.hpp"

namespace divergencesplitter {

struct CaptureStats {
    std::uint64_t frames_captured{};
    std::uint64_t frames_published{};
    double measured_fps{};
    std::string last_error;
    bool running{};
};

class CapturePipeline {
public:
    using FrameSink = std::function<void(std::shared_ptr<SharedFrameEvaluation>)>;
    using ErrorSink = std::function<void(std::string)>;

    CapturePipeline(
        std::unique_ptr<FrameSource> source,
        FrameNormalizer normalizer,
        FrameSink frame_sink,
        ErrorSink error_sink,
        std::shared_ptr<TimeProvider> time_provider = nullptr
    );
    ~CapturePipeline();

    CapturePipeline(const CapturePipeline&) = delete;
    CapturePipeline& operator=(const CapturePipeline&) = delete;

    void start();
    void stop();

    [[nodiscard]] CaptureStats stats() const;
    [[nodiscard]] std::shared_ptr<const cv::Mat> latest_preview() const;
    [[nodiscard]] std::string source_description() const;

private:
    void run();
    void publish_error(const std::string& message);

    std::unique_ptr<FrameSource> source_;
    FrameNormalizer normalizer_;
    FrameSink frame_sink_;
    ErrorSink error_sink_;
    std::shared_ptr<TimeProvider> time_provider_;

    mutable std::mutex mutex_;
    std::condition_variable cv_;
    bool stop_requested_{false};
    bool running_{false};
    std::shared_ptr<const cv::Mat> latest_preview_;
    std::string last_error_;
    std::uint64_t frames_captured_{};
    std::uint64_t frames_published_{};
    double measured_fps_{};

    std::thread thread_;
};

}  // namespace divergencesplitter
