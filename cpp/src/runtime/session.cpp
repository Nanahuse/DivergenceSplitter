#include "divergencesplitter/runtime/session.hpp"

#include "divergencesplitter/capture/configured_source.hpp"

#include <utility>
#include <variant>

#include "divergencesplitter/livesplit/client.hpp"
#include "divergencesplitter/scenario/scenario.hpp"

namespace divergencesplitter {

LoadedScenario load_profile_scenario(
    const std::filesystem::path& path,
    const SourceConfiguration& source
) {
    const auto options = std::visit(
        [](const auto& value) -> std::optional<ReferenceResizeOptions> {
            const auto& resize = value.transform.resize;
            if (!resize || !resize->resize_references) {
                return std::nullopt;
            }
            return ReferenceResizeOptions{
                {resize->width, resize->height}, resize->interpolation,
            };
        },
        source
    );
    try {
        return load_scenario(path, options);
    } catch (const ScenarioLoadError& error) {
        throw ConfigurationError(error.what());
    }
}

Session::Session(std::shared_ptr<TimeProvider> time_provider)
    : time_provider_(time_provider ? std::move(time_provider) : std::make_shared<SteadyTimeProvider>()) {}

Session::~Session() {
    stop();
}

void Session::apply_profile(const Profile& profile, const AppSettings& settings) {
    auto logger = std::make_shared<Logger>(
        default_log_path(),
        parse_log_level(settings.log_level)
    );
    logger->log(LogLevel::info, "profile.apply", std::to_string(profile.instances.size()) + " instance(s)");
    std::vector<std::unique_ptr<InstanceRuntime>> new_instances;
    new_instances.reserve(profile.instances.size());
    for (std::size_t index = 0; index < profile.instances.size(); ++index) {
        const auto& instance = profile.instances[index];
        const std::filesystem::path scenario_path{instance.scenario};
        if (!scenario_path.is_absolute()) {
            throw ConfigurationError(
                "scenario path must be an absolute path: " + instance.scenario
            );
        }
        auto loaded = load_profile_scenario(scenario_path, profile.source);
        LiveSplitClientOptions options;
        options.port = static_cast<std::uint16_t>(instance.connection.port);
        auto client = std::make_unique<LiveSplitBridgeClient>(std::move(options));
        InstanceRuntimeOptions runtime_options;
        runtime_options.reaction_time = std::chrono::milliseconds{settings.reaction_time_ms};
        runtime_options.logger = logger;
        new_instances.push_back(std::make_unique<InstanceRuntime>(
            static_cast<int>(index),
            std::move(loaded.scenario),
            std::move(client),
            runtime_options
        ));
    }

    auto source = create_frame_source(profile.source);
    FrameNormalizer normalizer = std::visit(
        [](const auto& value) { return create_frame_normalizer(value.transform); },
        profile.source
    );

    std::vector<InstanceRuntime*> sinks;
    sinks.reserve(new_instances.size());
    for (const auto& instance : new_instances) {
        sinks.push_back(instance.get());
    }

    auto capture = std::make_unique<CapturePipeline>(
        std::move(source),
        std::move(normalizer),
        [sinks](std::shared_ptr<SharedFrameEvaluation> shared) {
            for (auto* instance : sinks) {
                instance->publish_frame(shared);
            }
        },
        [this, logger](std::string message) {
            logger->log(LogLevel::error, "capture.error", message);
            std::scoped_lock lock{error_mutex_};
            last_error_ = std::move(message);
        },
        time_provider_
    );

    std::scoped_lock lock{mutex_};
    stop_locked();
    profile_ = profile;
    instances_ = std::move(new_instances);
    capture_ = std::move(capture);
    logger_ = logger;
    for (auto& instance : instances_) {
        instance->start();
    }
    capture_->start();
    running_ = true;
    {
        std::scoped_lock error_lock{error_mutex_};
        last_error_.clear();
    }
}

void Session::stop() {
    std::scoped_lock lock{mutex_};
    stop_locked();
}

void Session::stop_locked() {
    if (logger_) {
        logger_->log(LogLevel::info, "session.stop");
    }
    if (capture_) {
        capture_->stop();
        capture_.reset();
    }
    for (auto& instance : instances_) {
        instance->stop();
    }
    instances_.clear();
    running_ = false;
}

bool Session::running() const {
    std::scoped_lock lock{mutex_};
    return running_;
}

std::string Session::last_error() const {
    std::scoped_lock lock{error_mutex_};
    return last_error_;
}

Profile Session::profile() const {
    std::scoped_lock lock{mutex_};
    return profile_;
}

std::vector<InstanceDiagnosticsSnapshot> Session::instance_diagnostics() const {
    std::scoped_lock lock{mutex_};
    std::vector<InstanceDiagnosticsSnapshot> result;
    result.reserve(instances_.size());
    for (const auto& instance : instances_) {
        result.push_back(instance->diagnostics());
    }
    return result;
}

CaptureStats Session::capture_stats() const {
    std::scoped_lock lock{mutex_};
    if (!capture_) {
        return {};
    }
    return capture_->stats();
}

std::shared_ptr<const cv::Mat> Session::latest_preview() const {
    std::scoped_lock lock{mutex_};
    if (!capture_) {
        return nullptr;
    }
    return capture_->latest_preview();
}

void Session::request_reset_all() {
    std::scoped_lock lock{mutex_};
    for (auto& instance : instances_) {
        instance->request_manual_reset();
    }
}
}  // namespace divergencesplitter
