#include "divergencesplitter/capture/capture_pipeline.hpp"

#include <chrono>
#include <stdexcept>

namespace divergencesplitter {

CapturePipeline::CapturePipeline(
    std::unique_ptr<FrameSource> source,
    FrameNormalizer normalizer,
    FrameSink frame_sink,
    ErrorSink error_sink,
    std::shared_ptr<TimeProvider> time_provider
)
    : source_(std::move(source)),
      normalizer_(std::move(normalizer)),
      frame_sink_(std::move(frame_sink)),
      error_sink_(std::move(error_sink)),
      time_provider_(time_provider ? std::move(time_provider) : std::make_shared<SteadyTimeProvider>()) {
    if (!source_) {
        throw std::invalid_argument("frame source must not be null");
    }
    if (!frame_sink_) {
        throw std::invalid_argument("frame sink must not be null");
    }
}

CapturePipeline::~CapturePipeline() {
    stop();
}

void CapturePipeline::start() {
    std::scoped_lock lock{mutex_};
    if (running_) {
        return;
    }
    stop_requested_ = false;
    running_ = true;
    thread_ = std::thread(&CapturePipeline::run, this);
}

void CapturePipeline::stop() {
    {
        std::scoped_lock lock{mutex_};
        stop_requested_ = true;
    }
    cv_.notify_all();
    if (thread_.joinable()) {
        thread_.join();
    }
}

CaptureStats CapturePipeline::stats() const {
    std::scoped_lock lock{mutex_};
    return CaptureStats{
        frames_captured_,
        frames_published_,
        measured_fps_,
        last_error_,
        running_ && !stop_requested_,
    };
}

std::shared_ptr<const cv::Mat> CapturePipeline::latest_preview() const {
    std::scoped_lock lock{mutex_};
    return latest_preview_;
}

std::string CapturePipeline::source_description() const {
    return source_ ? source_->describe() : std::string{};
}

void CapturePipeline::publish_error(const std::string& message) {
    if (error_sink_) {
        error_sink_(message);
    }
}

void CapturePipeline::run() {
    std::string error;
    bool source_open = false;
    try {
        auto last_fps_at = std::chrono::steady_clock::now();
        std::uint64_t frames_since_sample = 0;
        while (true) {
            {
                std::scoped_lock lock{mutex_};
                if (stop_requested_) {
                    break;
                }
            }
            if (!source_open) {
                try {
                    source_->open();
                    source_open = true;
                } catch (const FrameSourceError& source_error) {
                    {
                        std::scoped_lock lock{mutex_};
                        if (stop_requested_) {
                            break;
                        }
                    }
                    if (source_error.retryable()) {
                        std::this_thread::sleep_for(std::chrono::milliseconds{100});
                        continue;
                    }
                    throw;
                }
            }
            try {
                MonotonicTime captured_at;
                cv::Mat image = source_->read(captured_at);
                if (image.empty()) {
                    throw FrameSourceError("frame source returned an empty frame", true);
                }
                cv::Mat normalized = normalizer_.normalize(image);
                auto now = time_provider_->now();
                auto shared = std::make_shared<SharedFrameEvaluation>(
                    SharedFrameEvaluation{Frame{normalized, captured_at}, now, {}}
                );
                {
                    std::scoped_lock lock{mutex_};
                    if (stop_requested_) {
                        break;
                    }
                    latest_preview_ =
                        std::make_shared<const cv::Mat>(normalized.clone());
                    ++frames_captured_;
                    ++frames_published_;
                    ++frames_since_sample;
                    const auto sample_now = std::chrono::steady_clock::now();
                    const auto elapsed = std::chrono::duration<double>(sample_now - last_fps_at);
                    if (elapsed.count() >= 1.0) {
                        measured_fps_ =
                            static_cast<double>(frames_since_sample) / elapsed.count();
                        frames_since_sample = 0;
                        last_fps_at = sample_now;
                    }
                }
                if (frame_sink_) {
                    frame_sink_(std::move(shared));
                }
            } catch (const FrameSourceError& source_error) {
                source_open = false;
                {
                    std::scoped_lock lock{mutex_};
                    if (stop_requested_) {
                        break;
                    }
                }
                if (source_error.retryable()) {
                    std::this_thread::sleep_for(std::chrono::milliseconds{100});
                    continue;
                }
                throw;
            }
        }
    } catch (const std::exception& failure) {
        error = failure.what();
    } catch (...) {
        error = "unknown capture failure";
    }

    {
        std::scoped_lock lock{mutex_};
        running_ = false;
        if (!error.empty()) {
            last_error_ = error;
        }
    }
    source_->close();
    if (!error.empty()) {
        publish_error(error);
    }
    cv_.notify_all();
}

}  // namespace divergencesplitter