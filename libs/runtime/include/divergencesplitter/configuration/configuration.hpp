#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include "divergencesplitter/capture/source_configuration.hpp"

namespace divergencesplitter {

struct ConnectionConfiguration {
    int port{54000};

    friend bool operator==(const ConnectionConfiguration&, const ConnectionConfiguration&) = default;
};

struct InstanceConfiguration {
    ConnectionConfiguration connection;
    std::string scenario;

    friend bool operator==(const InstanceConfiguration&, const InstanceConfiguration&) = default;
};

struct Profile {
    int version{2};
    SourceConfiguration source;
    std::vector<InstanceConfiguration> instances;

    friend bool operator==(const Profile&, const Profile&) = default;
};

struct ProfileLoadResult {
    Profile profile;
    bool migrated{false};
};

[[nodiscard]] ProfileLoadResult load_profile(const std::filesystem::path& path);
void save_profile(const std::filesystem::path& path, const Profile& profile);

struct AppSettings {
    int version{1};
    std::string log_level{"INFO"};
    int reaction_time_ms{};
    std::optional<std::string> last_profile;
    std::string theme{"light"};
};

[[nodiscard]] AppSettings load_app_settings(const std::filesystem::path& path);
void save_app_settings(const std::filesystem::path& path, const AppSettings& settings);

[[nodiscard]] std::filesystem::path application_data_directory();
[[nodiscard]] std::filesystem::path default_settings_path();
[[nodiscard]] std::filesystem::path default_log_path();
[[nodiscard]] std::string current_timestamp();

[[nodiscard]] std::optional<CameraBackend> parse_camera_backend_string(std::string_view value);
[[nodiscard]] ResizeInterpolation parse_interpolation_string(std::string_view value);
[[nodiscard]] std::optional<ResizeInterpolation> try_parse_interpolation_string(
    std::string_view value
);

}  // namespace divergencesplitter
