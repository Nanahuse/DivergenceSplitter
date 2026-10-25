#include "divergencesplitter/capture/frame_source.hpp"

#include <opencv2/videoio.hpp>

#include <chrono>
#include <cmath>
#include <stdexcept>
#include <string>
#include <thread>

namespace divergencesplitter {

namespace {
constexpr double kDefaultVideoFps = 30.0;
}

struct CameraFrameSource::Impl {
    cv::VideoCapture capture;
    bool opened{false};
};

CameraFrameSource::CameraFrameSource(CameraSourceOptions options)
    : options_(options), impl_(std::make_unique<Impl>()) {}

CameraFrameSource::~CameraFrameSource() = default;

void CameraFrameSource::open() {
    if (impl_->opened) {
        return;
    }
    const int backend = options_.backend == 0 ? cv::CAP_ANY : options_.backend;
    if (!impl_->capture.open(options_.device_index, backend)) {
        impl_->capture.release();
        throw FrameSourceError("cannot open camera device", true);
    }
    const auto configure = [this](int property, double value, std::string_view name) {
        if (value <= 0.0) {
            return;
        }
        if (!impl_->capture.set(property, value)) {
            impl_->capture.release();
            impl_->opened = false;
            throw FrameSourceError(
                "cannot configure camera " + std::string(name),
                false
            );
        }
    };
    configure(cv::CAP_PROP_FRAME_WIDTH, options_.width, "width");
    configure(cv::CAP_PROP_FRAME_HEIGHT, options_.height, "height");
    configure(cv::CAP_PROP_FPS, options_.fps, "fps");
    if (options_.request_60_fps) {
        impl_->capture.set(cv::CAP_PROP_FPS, 60.0);
    }
    impl_->opened = true;
}

cv::Mat CameraFrameSource::read(MonotonicTime& captured_at) {
    if (!impl_->opened) {
        throw FrameSourceError("camera is not open", true);
    }
    cv::Mat image;
    if (!impl_->capture.read(image) || image.empty()) {
        impl_->capture.release();
        impl_->opened = false;
        throw FrameSourceError("failed to read a frame from the camera", true);
    }
    captured_at = monotonic_now();
    return image;
}

void CameraFrameSource::close() noexcept {
    if (impl_) {
        impl_->capture.release();
        impl_->opened = false;
    }
}

std::string CameraFrameSource::describe() const {
    return "camera #" + std::to_string(options_.device_index);
}

struct VideoFileFrameSource::Impl {
    cv::VideoCapture capture;
    bool opened{false};
    double fps{kDefaultVideoFps};
    std::chrono::steady_clock::time_point playback_started{};
    std::uint64_t frames_read{};
};

VideoFileFrameSource::VideoFileFrameSource(VideoFileSourceOptions options)
    : options_(std::move(options)), impl_(std::make_unique<Impl>()) {}

VideoFileFrameSource::~VideoFileFrameSource() {
    close();
}

void VideoFileFrameSource::open() {
    if (impl_->opened) {
        return;
    }
    if (!impl_->capture.open(options_.path)) {
        impl_->capture.release();
        throw FrameSourceError("cannot open video file: " + options_.path, false);
    }
    const double recorded_fps = impl_->capture.get(cv::CAP_PROP_FPS);
    impl_->fps = recorded_fps > 0.0 ? recorded_fps : kDefaultVideoFps;
    impl_->playback_started = std::chrono::steady_clock::now();
    impl_->frames_read = 0;
    impl_->opened = true;
}

cv::Mat VideoFileFrameSource::read(MonotonicTime& captured_at) {
    if (!impl_->opened) {
        throw FrameSourceError("video source is not open", false);
    }
    const auto target = impl_->playback_started +
        std::chrono::duration_cast<std::chrono::steady_clock::duration>(
            std::chrono::duration<double>(static_cast<double>(impl_->frames_read) / impl_->fps)
        );
    const auto now = std::chrono::steady_clock::now();
    if (target > now) {
        std::this_thread::sleep_for(target - now);
    }

    cv::Mat image;
    if (!impl_->capture.read(image) || image.empty()) {
        const double total = impl_->capture.get(cv::CAP_PROP_FRAME_COUNT);
        const double position = impl_->capture.get(cv::CAP_PROP_POS_FRAMES);
        impl_->capture.release();
        impl_->opened = false;
        if (total <= 0.0 || position >= total) {
            throw FrameSourceError("reached the end of the video file", false);
        }
        throw FrameSourceError("failed to decode a video frame", false);
    }
    ++impl_->frames_read;
    captured_at = monotonic_now();
    return image;
}

void VideoFileFrameSource::close() noexcept {
    if (impl_) {
        impl_->capture.release();
        impl_->opened = false;
    }
}

std::string VideoFileFrameSource::describe() const {
    return options_.path;
}

struct NdiFrameSource::Impl {};

NdiFrameSource::NdiFrameSource(NdiSourceOptions options)
    : options_(std::move(options)), impl_(std::make_unique<Impl>()) {}

NdiFrameSource::~NdiFrameSource() = default;

void NdiFrameSource::open() {
    throw FrameSourceError(
        "NDI input requires the NDI SDK and is not part of this build. "
        "Use camera or video input until the NDI integration is enabled.",
        false
    );
}

cv::Mat NdiFrameSource::read(MonotonicTime&) {
    throw FrameSourceError("NDI source is not open", false);
}

void NdiFrameSource::close() noexcept {}

std::string NdiFrameSource::describe() const {
    return "NDI " + options_.name;
}

}  // namespace divergencesplitter
