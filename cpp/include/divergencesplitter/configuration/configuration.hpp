#pragma once

#include <cstdint>
#include <filesystem>
#include <optional>
#include <stdexcept>
#include <string>
#include <variant>
#include <vector>

#include "divergencesplitter/capture/normalizer.hpp"

namespace divergencesplitter {

class ConfigurationError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

enum class CameraBackend {
    direct_show,
    media_foundation,
};

[[nodiscard]] std::string_view to_string(CameraBackend backend) noexcept;
[[nodiscard]] std::optional<CameraBackend> parse_camera_backend(std::string_view value) noexcept;

struct CropConfiguration {
    int left{};
    int right{};
    int top{};
    int bottom{};

    friend bool operator==(const CropConfiguration&, const CropConfiguration&) = default;
};

struct ResizeConfiguration {
    int width{};
    int height{};
    ResizeInterpolation interpolation{ResizeInterpolation::area};
    bool resize_references{false};

    friend bool operator==(const ResizeConfiguration&, const ResizeConfiguration&) = default;
};

struct TransformConfiguration {
    std::optional<CropConfiguration> crop;
    std::optional<ResizeConfiguration> resize;

    friend bool operator==(const TransformConfiguration&, const TransformConfiguration&) = default;
};

struct CameraDeviceConfiguration {
    CameraBackend backend{CameraBackend::media_foundation};
    std::string name;
    int index{};
};

struct CameraModeConfiguration {
    int width{};
    int height{};
    double fps{};
    std::string subtype_guid;
};

struct CameraSourceConfiguration {
    CameraDeviceConfiguration device;
    CameraModeConfiguration mode;
    bool request_60_fps{false};
    TransformConfiguration transform;
};

struct VideoSourceConfiguration {
    std::string path;
    TransformConfiguration transform;
};

struct NdiSourceConfiguration {
    std::string name;
    TransformConfiguration transform;
};

using SourceConfiguration =
    std::variant<CameraSourceConfiguration, VideoSourceConfiguration, NdiSourceConfiguration>;

struct ConnectionConfiguration {
    int port{54000};
};

struct InstanceConfiguration {
    ConnectionConfiguration connection;
    std::string scenario;
};

struct Profile {
    int version{2};
    SourceConfiguration source;
    std::vector<InstanceConfiguration> instances;
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
