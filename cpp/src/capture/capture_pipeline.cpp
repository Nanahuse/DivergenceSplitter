#include "divergencesplitter/capture/capture_pipeline.hpp"

#include <opencv2/imgproc.hpp>

#include <chrono>
#include <stdexcept>

namespace divergencesplitter {
namespace {

int cv_interpolation(ResizeInterpolation interpolation) {
    switch (interpolation) {
        case ResizeInterpolation::area:
            return cv::INTER_AREA;
        case ResizeInterpolation::nearest:
            return cv::INTER_NEAREST;
        case ResizeInterpolation::linear:
            return cv::INTER_LINEAR;
        case ResizeInterpolation::cubic:
            return cv::INTER_CUBIC;
        case ResizeInterpolation::lanczos4:
            return cv::INTER_LANCZOS4;
    }
    return cv::INTER_AREA;
}

}  // namespace

std::string_view to_string(ResizeInterpolation interpolation) noexcept {
    switch (interpolation) {
        case ResizeInterpolation::area:
            return "area";
        case ResizeInterpolation::nearest:
            return "nearest";
        case ResizeInterpolation::linear:
            return "linear";
        case ResizeInterpolation::cubic:
            return "cubic";
        case ResizeInterpolation::lanczos4:
            return "lanczos4";
    }
    return "area";
}

std::optional<ResizeInterpolation> parse_resize_interpolation(std::string_view value) noexcept {
    if (value == "area") {
        return ResizeInterpolation::area;
    }
    if (value == "nearest") {
        return ResizeInterpolation::nearest;
    }
    if (value == "linear") {
        return ResizeInterpolation::linear;
    }
    if (value == "cubic") {
        return ResizeInterpolation::cubic;
    }
    if (value == "lanczos4") {
        return ResizeInterpolation::lanczos4;
    }
    return std::nullopt;
}

FrameNormalizer::FrameNormalizer(
    std::optional<CropMargins> crop_margins,
    std::optional<OutputSize> output_size,
    ResizeInterpolation interpolation
)
    : crop_margins_(crop_margins),
      output_size_(output_size),
      interpolation_(interpolation) {
    if (crop_margins_.has_value()) {
        const auto& margins = *crop_margins_;
        if (margins.left < 0 || margins.right < 0 || margins.top < 0 ||
            margins.bottom < 0) {
            throw std::invalid_argument("crop margins must be non-negative");
        }
    }
    if (output_size_.has_value()) {
        const auto& size = *output_size_;
        if (size.width <= 0 || size.height <= 0) {
            throw std::invalid_argument("output size must be positive");
        }
    }
}

cv::Mat FrameNormalizer::normalize(const cv::Mat& image) const {
    if (image.empty()) {
        throw FrameNormalizationError("frame is empty");
    }
    cv::Mat cropped;
    const cv::Mat* current = &image;
    if (crop_margins_.has_value()) {
        const auto& margins = *crop_margins_;
        if (margins.left + margins.right >= image.cols ||
            margins.top + margins.bottom >= image.rows) {
            throw FrameNormalizationError("crop margins do not fit in image");
        }
        const int width = image.cols - margins.left - margins.right;
        const int height = image.rows - margins.top - margins.bottom;
        cropped = image(cv::Rect{margins.left, margins.top, width, height}).clone();
        current = &cropped;
    }
    if (output_size_.has_value()) {
        cv::Mat resized;
        cv::resize(
            *current,
            resized,
            cv::Size{output_size_->width, output_size_->height},
            0.0,
            0.0,
            cv_interpolation(interpolation_)
        );
        return resized;
    }
    return *current;
}

}  // namespace divergencesplitter

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
                    if (stop_requested()) {
                        break;
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