#include "divergencesplitter/capture/ndi.hpp"
#include "divergencesplitter/capture/frame_source.hpp"

#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <mutex>
#include <utility>

namespace divergencesplitter {

std::shared_ptr<NdiApi> make_ndi_sdk_api();

NdiRuntime::NdiRuntime(std::shared_ptr<NdiApi> api) : api_(std::move(api)) {
    if (!api_ || !api_->initialize()) {
        throw FrameSourceError("NDI runtime initialization failed (CPU or runtime unsupported)", false);
    }
}

NdiRuntime::~NdiRuntime() { api_->destroy(); }

bool ndi_enabled() noexcept {
#if DIVERGENCESPLITTER_ENABLE_NDI
    return true;
#else
    return false;
#endif
}

std::shared_ptr<NdiRuntime> acquire_ndi_runtime() {
    // Keep the SDK initialized through application shutdown. This also avoids
    // racing the last receiver's destroy with a new discovery initialization.
    static auto runtime = std::make_shared<NdiRuntime>(make_ndi_sdk_api());
    return runtime;
}

std::vector<std::string> discover_ndi_sources(
    std::chrono::milliseconds timeout, std::shared_ptr<NdiRuntime> runtime
) {
    if (timeout.count() < 0) {
        throw std::invalid_argument("NDI discovery timeout must be nonnegative");
    }
    if (!runtime) runtime = acquire_ndi_runtime();
    auto& api = runtime->api();
    auto finder = api.create_finder();
    if (!finder) throw FrameSourceError("cannot create NDI source finder", false);
    const auto cleanup = [&api](void* value) { api.destroy_finder(value); };
    std::unique_ptr<void, decltype(cleanup)> guard{finder, cleanup};
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        const auto remaining = std::chrono::duration_cast<std::chrono::milliseconds>(
            deadline - std::chrono::steady_clock::now());
        api.wait_for_sources(finder, static_cast<std::uint32_t>(
            std::clamp<std::int64_t>(remaining.count(), 1, 100)));
    }
    auto names = api.sources(finder); // Copy before the finder is destroyed.
    std::sort(names.begin(), names.end());
    names.erase(std::unique(names.begin(), names.end()), names.end());
    return names;
}

cv::Mat ndi_video_to_bgr(const NdiVideoView& video) {
    const bool yuv = video.format == NdiPixelFormat::uyvy || video.format == NdiPixelFormat::uyva;
    const bool blue = video.format == NdiPixelFormat::bgra || video.format == NdiPixelFormat::bgrx;
    const bool red = video.format == NdiPixelFormat::rgba || video.format == NdiPixelFormat::rgbx;
    if (!yuv && !blue && !red) throw FrameSourceError("unsupported NDI video pixel format", false);
    const auto row_bytes = static_cast<std::int64_t>(video.width) * (yuv ? 2 : 4);
    if (!video.data || video.width <= 0 || video.height <= 0 ||
        video.stride < row_bytes || (yuv && video.width % 2 != 0)) {
        throw FrameSourceError("invalid NDI video dimensions or stride", false);
    }
    cv::Mat input{video.height, video.width, yuv ? CV_8UC2 : CV_8UC4,
                  const_cast<std::uint8_t*>(video.data), static_cast<std::size_t>(video.stride)};
    cv::Mat result;
    cv::cvtColor(input, result, yuv ? cv::COLOR_YUV2BGR_UYVY :
        (blue ? cv::COLOR_BGRA2BGR : cv::COLOR_RGBA2BGR));
    return result;
}

struct NdiFrameSource::Impl {
    std::shared_ptr<NdiRuntime> runtime;
    NdiApi::Handle receiver{};
};

NdiFrameSource::NdiFrameSource(NdiSourceOptions options, std::shared_ptr<NdiRuntime> runtime)
    : options_(std::move(options)), impl_(std::make_unique<Impl>()) {
    impl_->runtime = std::move(runtime);
}

NdiFrameSource::~NdiFrameSource() { close(); }

void NdiFrameSource::open() {
    if (impl_->receiver) return;
    if (options_.name.empty()) throw FrameSourceError("NDI source name is empty", false);
    if (!impl_->runtime) impl_->runtime = acquire_ndi_runtime();
    // Connect by saved name even if it is temporarily absent from discovery.
    // The SDK retains this connection and reconnects when the sender returns.
    impl_->receiver = impl_->runtime->api().create_receiver(options_.name);
    if (!impl_->receiver) throw FrameSourceError("cannot create NDI receiver: " + options_.name, false);
}

cv::Mat NdiFrameSource::read(MonotonicTime& captured_at) {
    if (!impl_->receiver) throw FrameSourceError("NDI receiver is not open", false);
    auto frame = impl_->runtime->api().capture(impl_->receiver, 50);
    if (frame.type == NdiFrameType::error) throw FrameSourceError("NDI receiver reported an error", false);
    if (frame.type != NdiFrameType::video) return {}; // A normal timeout/status/audio/metadata.
    captured_at = monotonic_now();
    return ndi_video_to_bgr(frame.video);
}

void NdiFrameSource::close() noexcept {
    if (impl_ && impl_->receiver) {
        impl_->runtime->api().destroy_receiver(std::exchange(impl_->receiver, nullptr));
    }
}

std::string NdiFrameSource::describe() const { return options_.name; }

}  // namespace divergencesplitter
