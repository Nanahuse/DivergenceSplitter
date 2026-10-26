#include "divergencesplitter/capture/frame_source.hpp"

#include <opencv2/videoio.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

namespace divergencesplitter {

namespace {
constexpr double kDefaultVideoFps = 30.0;

std::optional<int> fourcc_from_guid(std::string_view guid) {
    const auto first = guid.find('-');
    if (first == std::string_view::npos) {
        return std::nullopt;
    }
    const auto rest = guid.substr(first + 1);
    if (rest != "0000-0010-8000-00AA00389B71") {
        return std::nullopt;
    }
    unsigned long data1 = 0;
    try {
        data1 = std::stoul(std::string{guid.substr(0, first)}, nullptr, 16);
    } catch (const std::exception&) {
        return std::nullopt;
    }
    char fourcc[4]{};
    for (int shift = 0; shift < 32; shift += 8) {
        const auto character = static_cast<char>((data1 >> shift) & 0xff);
        if (character < 0x20 || character > 0x7e) {
            return std::nullopt;
        }
        fourcc[shift / 8] = character;
    }
    return cv::VideoWriter::fourcc(fourcc[0], fourcc[1], fourcc[2], fourcc[3]);
}
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
    if (backend == cv::CAP_DSHOW && !options_.subtype_guid.empty()) {
        const auto fourcc = fourcc_from_guid(options_.subtype_guid);
        if (!fourcc.has_value()) {
            impl_->capture.release();
            impl_->opened = false;
            throw FrameSourceError(
                "DirectShow/OpenCV cannot select the configured camera subtype: " +
                    options_.subtype_guid,
                false
            );
        }
        if (!impl_->capture.set(cv::CAP_PROP_FOURCC, *fourcc)) {
            impl_->capture.release();
            impl_->opened = false;
            throw FrameSourceError(
                "DirectShow rejected the configured camera subtype: " +
                    options_.subtype_guid,
                false
            );
        }
        const int actual = static_cast<int>(impl_->capture.get(cv::CAP_PROP_FOURCC));
        if (actual == 0 || actual != *fourcc) {
            impl_->capture.release();
            impl_->opened = false;
            throw FrameSourceError(
                "DirectShow did not confirm the configured camera subtype: " +
                    options_.subtype_guid,
                false
            );
        }
    }
    if (options_.request_60_fps) {
        impl_->capture.set(cv::CAP_PROP_FPS, 60.0);
    }
    if (options_.enforce_mode) {
        const int width = static_cast<int>(impl_->capture.get(cv::CAP_PROP_FRAME_WIDTH));
        const int height = static_cast<int>(impl_->capture.get(cv::CAP_PROP_FRAME_HEIGHT));
        const double fps = impl_->capture.get(cv::CAP_PROP_FPS);
        const bool size_mismatch = width != options_.width || height != options_.height;
        const bool fps_mismatch = !options_.request_60_fps && fps > 0.0 &&
            std::abs(fps - options_.fps) > std::max(1e-3, options_.fps * 1e-6);
        if (size_mismatch || fps_mismatch) {
            impl_->capture.release();
            impl_->opened = false;
            throw FrameSourceError(
                "camera rejected the configured capture mode: expected " +
                    std::to_string(options_.width) + "x" + std::to_string(options_.height) +
                    "@" + std::to_string(options_.fps) + ", got " + std::to_string(width) +
                    "x" + std::to_string(height) + "@" + std::to_string(fps),
                false
            );
        }
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
