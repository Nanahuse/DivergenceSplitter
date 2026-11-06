#include "divergencesplitter/capture/frame_source.hpp"

#include <opencv2/videoio.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#ifdef _WIN32
#include <Windows.h>
#endif

#include "divergencesplitter/text.hpp"

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

#ifdef _WIN32
bool is_ascii(std::wstring_view value) {
    return std::all_of(value.begin(), value.end(), [](wchar_t character) {
        return character >= 0 && character <= 0x7f;
    });
}

std::string narrow_ascii(std::wstring_view value) {
    std::string result;
    result.reserve(value.size());
    for (const wchar_t character : value) {
        result.push_back(static_cast<char>(character));
    }
    return result;
}

std::optional<std::filesystem::path> ascii_short_path(
    const std::filesystem::path& path
) {
    const DWORD size = GetShortPathNameW(path.c_str(), nullptr, 0);
    if (size == 0) {
        return std::nullopt;
    }
    std::wstring buffer(size, L'\0');
    const DWORD written = GetShortPathNameW(path.c_str(), buffer.data(), size);
    if (written == 0 || written >= size) {
        return std::nullopt;
    }
    buffer.resize(written);
    if (!is_ascii(buffer)) {
        return std::nullopt;
    }
    return std::filesystem::path{buffer};
}

std::string narrow_acp(std::wstring_view value) {
    if (value.empty()) {
        return {};
    }
    const int size = WideCharToMultiByte(
        CP_ACP,
        0,
        value.data(),
        static_cast<int>(value.size()),
        nullptr,
        0,
        nullptr,
        nullptr
    );
    if (size <= 0) {
        return {};
    }
    std::string result(static_cast<std::size_t>(size), '\0');
    WideCharToMultiByte(
        CP_ACP,
        0,
        value.data(),
        static_cast<int>(value.size()),
        result.data(),
        size,
        nullptr,
        nullptr
    );
    return result;
}

// OpenCV on Windows treats narrow paths as the active code page. For non-ASCII
// paths, try an ASCII short path or a temporary hard link before falling back.
struct VideoOpenPaths {
    VideoOpenPaths() = default;
    VideoOpenPaths(const VideoOpenPaths&) = delete;
    VideoOpenPaths& operator=(const VideoOpenPaths&) = delete;
    VideoOpenPaths(VideoOpenPaths&&) = default;
    VideoOpenPaths& operator=(VideoOpenPaths&&) = default;

    std::vector<std::string> candidates;
    std::vector<std::filesystem::path> links;

    ~VideoOpenPaths() {
        std::error_code ignored;
        for (const auto& link : links) {
            std::filesystem::remove(link, ignored);
        }
    }
};

VideoOpenPaths video_open_paths(const std::string& utf8_path) {
    VideoOpenPaths result;
    const auto path = path_from_utf8(utf8_path);
    const auto wide_path = path.wstring();
    if (is_ascii(wide_path)) {
        result.candidates.push_back(utf8_path);
        return result;
    }

    if (const auto short_path = ascii_short_path(path)) {
        result.candidates.push_back(narrow_ascii(short_path->wstring()));
    }

    const auto extension = path.extension().wstring();
    const std::wstring unique = std::to_wstring(GetCurrentProcessId()) + L"-" +
                                std::to_wstring(GetTickCount64());
    const auto try_link = [&](const std::filesystem::path& link) {
        if (CreateHardLinkW(link.c_str(), path.c_str(), nullptr) == 0) {
            return;
        }
        result.links.push_back(link);
        if (is_ascii(link.wstring())) {
            result.candidates.push_back(narrow_ascii(link.wstring()));
        } else if (const auto short_link = ascii_short_path(link)) {
            result.candidates.push_back(narrow_ascii(short_link->wstring()));
        }
    };

    std::error_code error;
    const auto temporary = std::filesystem::temp_directory_path(error);
    if (!error) {
        try_link(temporary / (L"ds-video-" + unique + extension));
    }
    try_link(path.parent_path() / (L".ds-video-" + unique + extension));

    const auto fallback = narrow_acp(wide_path);
    if (!fallback.empty()) {
        result.candidates.push_back(fallback);
    }
    if (result.candidates.empty()) {
        result.candidates.push_back(utf8_path);
    }
    return result;
}
#endif
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

FrameSource::Format CameraFrameSource::opened_format() const {
    if (!impl_->opened) return {};
    return {
        static_cast<int>(impl_->capture.get(cv::CAP_PROP_FRAME_WIDTH)),
        static_cast<int>(impl_->capture.get(cv::CAP_PROP_FRAME_HEIGHT)),
        impl_->capture.get(cv::CAP_PROP_FPS),
        impl_->capture.getBackendName(),
    };
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
    // The built-in AVI/MJPEG reader needs no OS codec or GPU initialization.
    // CAP_ANY tries MSMF first on Windows; even tiny local MJPEG recordings can
    // then block in hardware/codec discovery before the first frame or Stop.
    // Let other video formats retain the normal platform backend fallback.
    bool opened = false;
#ifdef _WIN32
    VideoOpenPaths paths = video_open_paths(options_.path);
    for (const auto& candidate : paths.candidates) {
        if (impl_->capture.open(candidate, cv::CAP_OPENCV_MJPEG)) {
            opened = true;
            break;
        }
        impl_->capture.release();
        if (impl_->capture.open(candidate, cv::CAP_ANY)) {
            opened = true;
            break;
        }
        impl_->capture.release();
    }
#else
    opened = impl_->capture.open(options_.path, cv::CAP_OPENCV_MJPEG) ||
             impl_->capture.open(options_.path, cv::CAP_ANY);
#endif
    if (!opened) {
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
        // Keep low-FPS recordings interruptible by CapturePipeline/preview Stop.
        std::this_thread::sleep_for(std::min(target - now,
            std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::milliseconds{50})));
        if (std::chrono::steady_clock::now() < target) return {};
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

FrameSource::Format VideoFileFrameSource::opened_format() const {
    if (!impl_->opened) return {};
    return {
        static_cast<int>(impl_->capture.get(cv::CAP_PROP_FRAME_WIDTH)),
        static_cast<int>(impl_->capture.get(cv::CAP_PROP_FRAME_HEIGHT)),
        impl_->fps,
        impl_->capture.getBackendName(),
    };
}

}  // namespace divergencesplitter
