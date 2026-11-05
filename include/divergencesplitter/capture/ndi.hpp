#pragma once

#include <chrono>
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

#include <opencv2/core.hpp>

namespace divergencesplitter {

enum class NdiPixelFormat { uyvy, uyva, bgra, bgrx, rgba, rgbx, unsupported };
enum class NdiFrameType { none, video, audio, metadata, status_change, error };

struct NdiVideoView {
    int width{};
    int height{};
    int stride{};
    NdiPixelFormat format{NdiPixelFormat::unsupported};
    const std::uint8_t* data{};
};

// The lease frees the SDK buffer even if conversion throws. BGR output never
// aliases this buffer. Audio and metadata leases are released without decoding.
struct NdiCapturedFrame {
    NdiFrameType type{NdiFrameType::none};
    NdiVideoView video;
    std::shared_ptr<void> lease;
};

// SDK boundary: tests can exercise lifetimes and failure paths without the SDK.
class NdiApi {
public:
    using Handle = void*;
    virtual ~NdiApi() = default;
    virtual bool initialize() = 0;
    virtual void destroy() noexcept = 0;
    virtual std::string version() const = 0;
    virtual Handle create_finder() = 0;
    virtual void destroy_finder(Handle finder) noexcept = 0;
    virtual void wait_for_sources(Handle finder, std::uint32_t timeout_ms) = 0;
    virtual std::vector<std::string> sources(Handle finder) = 0;
    virtual Handle create_receiver(const std::string& name) = 0;
    virtual void destroy_receiver(Handle receiver) noexcept = 0;
    virtual NdiCapturedFrame capture(Handle receiver, std::uint32_t timeout_ms) = 0;
};

class NdiRuntime final {
public:
    explicit NdiRuntime(std::shared_ptr<NdiApi> api);
    ~NdiRuntime();
    NdiRuntime(const NdiRuntime&) = delete;
    NdiRuntime& operator=(const NdiRuntime&) = delete;
    NdiApi& api() const noexcept { return *api_; }

private:
    std::shared_ptr<NdiApi> api_;
};

[[nodiscard]] bool ndi_enabled() noexcept;
// All default finders and receivers share a single initialized runtime.
[[nodiscard]] std::shared_ptr<NdiRuntime> acquire_ndi_runtime();
[[nodiscard]] std::vector<std::string> discover_ndi_sources(
    std::chrono::milliseconds timeout = std::chrono::milliseconds{1500},
    std::shared_ptr<NdiRuntime> runtime = nullptr
);
[[nodiscard]] cv::Mat ndi_video_to_bgr(const NdiVideoView& video);

}  // namespace divergencesplitter
