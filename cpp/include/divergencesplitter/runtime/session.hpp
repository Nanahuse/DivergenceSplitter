#pragma once

#include <opencv2/core.hpp>

#include <memory>
#include <mutex>
#include <string>
#include <vector>

#include "divergencesplitter/capture/capture_pipeline.hpp"
#include "divergencesplitter/clock.hpp"
#include "divergencesplitter/configuration/configuration.hpp"
#include "divergencesplitter/runtime/diagnostics.hpp"
#include "divergencesplitter/runtime/instance_runtime.hpp"
#include "divergencesplitter/runtime/logging.hpp"
#include "divergencesplitter/scenario/scenario.hpp"

namespace divergencesplitter {

// Shared by Apply validation and runtime startup, including reference transforms.
[[nodiscard]] LoadedScenario load_profile_scenario(
    const std::filesystem::path& path,
    const SourceConfiguration& source
);

class Session {
public:
    explicit Session(std::shared_ptr<TimeProvider> time_provider = nullptr);
    ~Session();

    Session(const Session&) = delete;
    Session& operator=(const Session&) = delete;

    void apply_profile(const Profile& profile, const AppSettings& settings);
    void stop();

    [[nodiscard]] bool running() const;
    [[nodiscard]] std::string last_error() const;
    [[nodiscard]] Profile profile() const;
    [[nodiscard]] std::vector<InstanceDiagnosticsSnapshot> instance_diagnostics() const;
    [[nodiscard]] CaptureStats capture_stats() const;
    [[nodiscard]] std::shared_ptr<const cv::Mat> latest_preview() const;
    void request_reset_all();

private:
    void stop_locked();
    [[nodiscard]] std::unique_ptr<FrameSource> create_source(const SourceConfiguration& source) const;
    [[nodiscard]] static FrameNormalizer create_normalizer(const TransformConfiguration& transform);

    std::shared_ptr<TimeProvider> time_provider_;
    mutable std::mutex mutex_;
    mutable std::mutex error_mutex_;
    Profile profile_;
    bool running_{false};
    std::string last_error_;
    std::vector<std::unique_ptr<InstanceRuntime>> instances_;
    std::unique_ptr<CapturePipeline> capture_;
    std::shared_ptr<Logger> logger_;
};

}  // namespace divergencesplitter
