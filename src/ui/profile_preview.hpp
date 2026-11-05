#pragma once

#include <QImage>

#include <condition_variable>
#include <functional>
#include <mutex>
#include <optional>
#include <thread>

#include "divergencesplitter/capture/configured_source.hpp"

namespace divergencesplitter::ui {

struct ProfilePreviewSnapshot {
    QImage image;
    FrameSource::Format input;
    double measured_fps{};
    std::string error;
    std::uint64_t revision{};
};

// Owns the input exclusively. No widgets or Session state are accessed here.
class ProfilePreview {
public:
    using SourceFactory = std::function<std::unique_ptr<FrameSource>(const SourceConfiguration&)>;
    explicit ProfilePreview(SourceFactory factory = create_frame_source);
    ~ProfilePreview();
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
