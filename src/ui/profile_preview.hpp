#pragma once

#include <opencv2/core.hpp>

#include <condition_variable>
#include <cstdint>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

#include "divergencesplitter/capture/configured_source.hpp"

namespace divergencesplitter::ui {

struct ProfilePreviewSnapshot {
    cv::Mat image;
    FrameSource::Format input;
    double measured_fps{};
    std::string error;
    std::uint64_t revision{};
};

// Owns the input exclusively. No GUI or Session state is accessed here.
class ProfilePreview {
public:
    using SourceFactory = std::function<std::unique_ptr<FrameSource>(const SourceConfiguration&)>;
    explicit ProfilePreview(SourceFactory factory = create_frame_source);
    ~ProfilePreview();
    ProfilePreview(const ProfilePreview&) = delete;
    ProfilePreview& operator=(const ProfilePreview&) = delete;

    void configure(const SourceConfiguration& source);
    void stop();
    [[nodiscard]] ProfilePreviewSnapshot snapshot() const;

private:
    void run();
    SourceFactory factory_;
    mutable std::mutex mutex_;
    std::condition_variable cv_;
    std::optional<SourceConfiguration> requested_;
    std::uint64_t revision_{};
    bool stopping_{};
    ProfilePreviewSnapshot snapshot_;
    std::thread thread_;
};

}  // namespace divergencesplitter::ui
