#include "divergencesplitter/configuration/configuration.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>

namespace divergencesplitter {
namespace {

using json = nlohmann::json;
using StringSet = std::set<std::string>;

constexpr int kProfileVersion = 2;
constexpr int kAppSettingsVersion = 1;
constexpr int kLegacyMigrationPortStart = 54000;
constexpr int kMinimumPort = 1;
constexpr int kMaximumPort = 65535;

[[noreturn]] void fail(const std::string& message) {
    throw ConfigurationError(message);
}

const json& require_object(const json& value, std::string_view path) {
    if (!value.is_object()) {
        fail(std::string(path) + " must be an object");
    }
    return value;
}

const json& require_array(const json& value, std::string_view path) {
    if (!value.is_array()) {
        fail(std::string(path) + " must be an array");
    }
    return value;
}

void check_keys(
    const json& value,
    const StringSet& required,
    const StringSet& optional = {},
    bool allow_unknown = false
) {
    StringSet present;
    for (auto it = value.begin(); it != value.end(); ++it) {
        present.insert(it.key());
    }
    for (const auto& key : required) {
        if (!present.contains(key)) {
            fail("missing field: " + key);
        }
    }
    if (!allow_unknown) {
        for (const auto& key : present) {
            if (!required.contains(key) && !optional.contains(key)) {
                fail("unknown field: " + key);
            }
        }
    }
}

const json& member(const json& object, const std::string& key, std::string_view path) {
    const auto it = object.find(key);
    if (it == object.end()) {
        fail(std::string(path) + "." + key + " is missing");
    }
    return *it;
}

std::string string_value(const json& value, std::string_view path) {
    if (!value.is_string()) {
        fail(std::string(path) + " must be a string");
    }
    return value.get<std::string>();
}

int integer_value(const json& value, std::string_view path) {
    if (!value.is_number_integer()) {
        fail(std::string(path) + " must be an integer");
    }
    return value.get<int>();
}

double number_value(const json& value, std::string_view path) {
    if (!value.is_number()) {
        fail(std::string(path) + " must be a number");
    }
    return value.get<double>();
}

bool boolean_value(const json& value, std::string_view path) {
    if (!value.is_boolean()) {
        fail(std::string(path) + " must be a boolean");
    }
    return value.get<bool>();
}

std::optional<CameraBackend> camera_backend(const json& value, std::string_view path) {
    const std::string text = string_value(value, path);
    const auto parsed = parse_camera_backend(text);
    if (!parsed.has_value()) {
        fail("unsupported " + std::string(path) + ": " + text);
    }
    return parsed;
}

TransformConfiguration parse_transform(
    const json& value,
    std::string_view path
) {
    const auto& object = require_object(value, path);
    check_keys(object, {"crop", "resize"});
    TransformConfiguration result;
    const auto& crop_value = object.at("crop");
    if (!crop_value.is_null()) {
        const auto& crop = require_object(crop_value, std::string(path) + ".crop");
        check_keys(crop, {"left", "right", "top", "bottom"});
        result.crop = CropConfiguration{
            integer_value(crop.at("left"), std::string(path) + ".crop.left"),
            integer_value(crop.at("right"), std::string(path) + ".crop.right"),
            integer_value(crop.at("top"), std::string(path) + ".crop.top"),
            integer_value(crop.at("bottom"), std::string(path) + ".crop.bottom"),
        };
        if (result.crop->left < 0 || result.crop->right < 0 ||
            result.crop->top < 0 || result.crop->bottom < 0) {
            fail(std::string(path) + ".crop must be non-negative");
        }
    }
    const auto& resize_value = object.at("resize");
    if (!resize_value.is_null()) {
        const auto& resize = require_object(resize_value, std::string(path) + ".resize");
        check_keys(resize, {"width", "height"}, {"interpolation", "resize_references"});
        result.resize = ResizeConfiguration{
            integer_value(resize.at("width"), std::string(path) + ".resize.width"),
            integer_value(resize.at("height"), std::string(path) + ".resize.height"),
            ResizeInterpolation::area,
            resize.contains("resize_references")
                ? boolean_value(resize.at("resize_references"), std::string(path) + ".resize.resize_references")
                : false,
        };
        if (result.resize->width <= 0 || result.resize->height <= 0) {
            fail(std::string(path) + ".resize dimensions must be positive");
        }
        if (resize.contains("interpolation")) {
            const auto parsed = try_parse_interpolation_string(
                string_value(resize.at("interpolation"), std::string(path) + ".resize.interpolation")
            );
            if (!parsed.has_value()) {
                fail(std::string(path) + ".resize.interpolation is invalid");
            }
            result.resize->interpolation = *parsed;
        }
    }
    return result;
}

SourceConfiguration parse_source(const json& value) {
    const auto& source = require_object(value, "source");
    const std::string type = string_value(member(source, "type", "source"), "source.type");
    if (type == "camera") {
        check_keys(source, {"type", "device", "mode", "request_60_fps"}, {"transform"});
        const auto& device_value = require_object(member(source, "device", "source"), "source.device");
        check_keys(device_value, {"backend", "name", "index"});
        CameraDeviceConfiguration device{
            *camera_backend(device_value.at("backend"), "source.device.backend"),
            string_value(device_value.at("name"), "source.device.name"),
            integer_value(device_value.at("index"), "source.device.index"),
        };
        if (device.name.empty()) {
            fail("camera device name must not be empty");
        }
        if (device.index < 0) {
            fail("camera device index must be non-negative");
        }
        const auto& mode_value = require_object(member(source, "mode", "source"), "source.mode");
        check_keys(mode_value, {"width", "height", "fps", "subtype_guid"});
        CameraModeConfiguration mode{
            integer_value(mode_value.at("width"), "source.mode.width"),
            integer_value(mode_value.at("height"), "source.mode.height"),
            number_value(mode_value.at("fps"), "source.mode.fps"),
            string_value(mode_value.at("subtype_guid"), "source.mode.subtype_guid"),
        };
        if (mode.width <= 0 || mode.height <= 0 || mode.fps <= 0.0 || mode.subtype_guid.empty()) {
            fail("camera mode is invalid");
        }
        TransformConfiguration transform;
        if (source.contains("transform")) {
            transform = parse_transform(source.at("transform"), "source.transform");
        }
        return CameraSourceConfiguration{
            std::move(device),
            std::move(mode),
            boolean_value(source.at("request_60_fps"), "source.request_60_fps"),
            std::move(transform),
        };
    }
    if (type == "video") {
        check_keys(source, {"type", "path"}, {"transform"});
        const std::string path = string_value(member(source, "path", "source"), "source.path");
        if (path.empty()) {
            fail("video path must not be empty");
        }
        TransformConfiguration transform;
        if (source.contains("transform")) {
            transform = parse_transform(source.at("transform"), "source.transform");
        }
        return VideoSourceConfiguration{path, std::move(transform)};
    }
    if (type == "ndi") {
        check_keys(source, {"type", "name"}, {"transform"});
        const std::string name = string_value(member(source, "name", "source"), "source.name");
        if (name.empty()) {
            fail("NDI source name must not be empty");
        }
        TransformConfiguration transform;
        if (source.contains("transform")) {
            transform = parse_transform(source.at("transform"), "source.transform");
        }
        return NdiSourceConfiguration{name, std::move(transform)};
    }
    fail("unsupported source type: " + type);
}

ConnectionConfiguration parse_connection(const json& value, std::string_view path) {
    const auto& connection = require_object(value, path);
    check_keys(connection, {"port"});
    const int port = integer_value(member(connection, "port", path), std::string(path) + ".port");
    if (port < kMinimumPort || port > kMaximumPort) {
        fail(std::string(path) + ".port must be between 1 and 65535");
    }
    return ConnectionConfiguration{port};
}

InstanceConfiguration parse_instance(const json& value, std::size_t index) {
    const std::string path = "instances[" + std::to_string(index) + "]";
    const auto& instance = require_object(value, path);
    check_keys(instance, {"connection", "scenario"});
    const std::string scenario = string_value(instance.at("scenario"), path + ".scenario");
    if (scenario.empty()) {
        fail(path + ".scenario must not be empty");
    }
    return InstanceConfiguration{
        parse_connection(instance.at("connection"), path + ".connection"),
        scenario,
    };
}

InstanceConfiguration parse_legacy_instance(
    const json& value,
    std::size_t index,
    int port
) {
    const std::string path = "instances[" + std::to_string(index) + "]";
    const auto& instance = require_object(value, path);
    check_keys(instance, {"connection", "scenario"});
    const auto& connection = require_object(instance.at("connection"), path + ".connection");
    check_keys(connection, {"rpc_endpoint", "event_endpoint"});
    (void)string_value(connection.at("rpc_endpoint"), path + ".connection.rpc_endpoint");
    (void)string_value(connection.at("event_endpoint"), path + ".connection.event_endpoint");
    const std::string scenario = string_value(instance.at("scenario"), path + ".scenario");
    if (scenario.empty()) {
        fail(path + ".scenario must not be empty");
    }
    return InstanceConfiguration{ConnectionConfiguration{port}, scenario};
}

json source_to_json(const SourceConfiguration& source) {
    return std::visit(
        [](const auto& value) -> json {
            using Value = std::decay_t<decltype(value)>;
            json result;
            if constexpr (std::is_same_v<Value, CameraSourceConfiguration>) {
                result = {
                    {"type", "camera"},
                    {"device",
                     {
                         {"backend", std::string{to_string(value.device.backend)}},
                         {"name", value.device.name},
                         {"index", value.device.index},
                     }},
                    {"mode",
                     {
                         {"width", value.mode.width},
                         {"height", value.mode.height},
                         {"fps", value.mode.fps},
                         {"subtype_guid", value.mode.subtype_guid},
                     }},
                    {"request_60_fps", value.request_60_fps},
                };
            } else if constexpr (std::is_same_v<Value, VideoSourceConfiguration>) {
                result = {{"type", "video"}, {"path", value.path}};
            } else {
                result = {{"type", "ndi"}, {"name", value.name}};
            }
            if constexpr (requires { value.transform; }) {
                const auto& transform = value.transform;
                result["transform"] = {
                    {"crop",
                     transform.crop.has_value()
                         ? json{{"left", transform.crop->left},
                                {"right", transform.crop->right},
                                {"top", transform.crop->top},
                                {"bottom", transform.crop->bottom}}
                         : json(nullptr)},
                    {"resize",
                     transform.resize.has_value()
                         ? json{{"width", transform.resize->width},
                                {"height", transform.resize->height},
                                {"interpolation", std::string{to_string(transform.resize->interpolation)}},
                                {"resize_references", transform.resize->resize_references}}
                         : json(nullptr)},
                };
            }
            return result;
        },
        source
    );
}

std::string read_file(const std::filesystem::path& path) {
    std::ifstream stream{path, std::ios::binary};
    if (!stream) {
        fail("could not open configuration file: " + path.string());
    }
    std::ostringstream content;
    content << stream.rdbuf();
    return content.str();
}

json parse_json_file(const std::filesystem::path& path) {
    try {
        return json::parse(read_file(path));
    } catch (const ConfigurationError&) {
        throw;
    } catch (const std::exception& error) {
        fail("could not parse configuration file: " + std::string(error.what()));
    }
}

}  // namespace

std::string_view to_string(CameraBackend backend) noexcept {
    switch (backend) {
        case CameraBackend::direct_show:
            return "direct_show";
        case CameraBackend::media_foundation:
            return "media_foundation";
    }
    return "media_foundation";
}

std::optional<CameraBackend> parse_camera_backend(std::string_view value) noexcept {
    if (value == "direct_show") {
        return CameraBackend::direct_show;
    }
    if (value == "media_foundation") {
        return CameraBackend::media_foundation;
    }
    return std::nullopt;
}

std::optional<CameraBackend> parse_camera_backend_string(std::string_view value) {
    return parse_camera_backend(value);
}

ResizeInterpolation parse_interpolation_string(std::string_view value) {
    const auto parsed = try_parse_interpolation_string(value);
    if (!parsed.has_value()) {
        fail("unsupported interpolation: " + std::string(value));
    }
    return *parsed;
}

std::optional<ResizeInterpolation> try_parse_interpolation_string(std::string_view value) {
    return parse_resize_interpolation(value);
}

ProfileLoadResult load_profile(const std::filesystem::path& path) {
    const auto document = parse_json_file(path);
    const auto& root = require_object(document, "profile");
    check_keys(root, {"version", "source", "instances"});
    const int version = integer_value(root.at("version"), "version");
    SourceConfiguration source = parse_source(root.at("source"));
    std::vector<InstanceConfiguration> instances;
    bool migrated = false;
    const auto& values = require_array(root.at("instances"), "instances");
    if (version == 1) {
        migrated = true;
        for (std::size_t index = 0; index < values.size(); ++index) {
            const int port = kLegacyMigrationPortStart + static_cast<int>(index);
            if (port > kMaximumPort) {
                fail("cannot migrate instances: WebSocket port exceeds 65535");
            }
            instances.push_back(parse_legacy_instance(values.at(index), index, port));
        }
    } else if (version == kProfileVersion) {
        for (std::size_t index = 0; index < values.size(); ++index) {
            instances.push_back(parse_instance(values.at(index), index));
        }
    } else {
        fail("unsupported profile version: " + std::to_string(version));
    }

    for (const auto& instance : instances) {
        const std::filesystem::path scenario_path{instance.scenario};
        if (!scenario_path.is_absolute()) {
            fail("scenario path must be an absolute path: " + instance.scenario);
        }
    }
    if (std::holds_alternative<VideoSourceConfiguration>(source)) {
        const auto& video = std::get<VideoSourceConfiguration>(source);
        if (!std::filesystem::path{video.path}.is_absolute()) {
            fail("video source path must be an absolute path: " + video.path);
        }
    }

    return ProfileLoadResult{Profile{kProfileVersion, std::move(source), std::move(instances)}, migrated};
}

void save_profile(const std::filesystem::path& path, const Profile& profile) {
    json instances = json::array();
    for (const auto& instance : profile.instances) {
        instances.push_back({
            {"connection", {{"port", instance.connection.port}}},
            {"scenario", instance.scenario},
        });
    }
    const json document = {
        {"version", kProfileVersion},
        {"source", source_to_json(profile.source)},
        {"instances", std::move(instances)},
    };
    std::ofstream stream{path, std::ios::binary};
    if (!stream) {
        fail("could not write profile: " + path.string());
    }
    stream << document.dump(2) << '\n';
}

AppSettings load_app_settings(const std::filesystem::path& path) {
    const auto document = parse_json_file(path);
    const auto& root = require_object(document, "app settings");
    check_keys(root, {"version", "log_level", "reaction_time_ms"}, {"last_profile", "ui"});
    const int version = integer_value(root.at("version"), "version");
    if (version != kAppSettingsVersion) {
        fail("unsupported app settings version: " + std::to_string(version));
    }
    const std::string log_level = string_value(root.at("log_level"), "log_level");
    const std::set<std::string> levels{"OFF", "DEBUG", "INFO", "WARNING", "ERROR"};
    if (!levels.contains(log_level)) {
        fail("unsupported log level: " + log_level);
    }
    const int reaction_time_ms = integer_value(root.at("reaction_time_ms"), "reaction_time_ms");
    if (reaction_time_ms < 0) {
        fail("reaction_time_ms must be non-negative");
    }
    std::optional<std::string> last_profile;
    if (root.contains("last_profile") && !root.at("last_profile").is_null()) {
        last_profile = string_value(root.at("last_profile"), "last_profile");
        if (!std::filesystem::path{*last_profile}.is_absolute()) {
            fail("last_profile must be an absolute path");
        }
    }
    std::string theme = "light";
    if (root.contains("ui")) {
        const auto& ui = require_object(root.at("ui"), "ui");
        check_keys(ui, {}, {"theme"});
        if (ui.contains("theme")) {
            theme = string_value(ui.at("theme"), "ui.theme");
        }
        if (theme != "light" && theme != "dark") {
            fail("unsupported ui.theme: " + theme);
        }
    }
    return AppSettings{version, log_level, reaction_time_ms, last_profile, theme};
}

void save_app_settings(const std::filesystem::path& path, const AppSettings& settings) {
    if (path.has_parent_path()) {
        std::filesystem::create_directories(path.parent_path());
    }
    json document = {
        {"version", kAppSettingsVersion},
        {"log_level", settings.log_level},
        {"reaction_time_ms", settings.reaction_time_ms},
        {"last_profile", settings.last_profile ? json(*settings.last_profile) : json(nullptr)},
        {"ui", {{"theme", settings.theme}}},
    };
    std::ofstream stream{path, std::ios::binary};
    if (!stream) {
        fail("could not write app settings: " + path.string());
    }
    stream << document.dump(2) << '\n';
}

std::filesystem::path application_data_directory() {
#ifdef _WIN32
    if (const char* appdata = std::getenv("APPDATA"); appdata != nullptr && *appdata != '\0') {
        return std::filesystem::path{appdata} / "DivergenceSplitter";
    }
    return std::filesystem::path{std::getenv("USERPROFILE")} / "AppData" / "Roaming" /
           "DivergenceSplitter";
#else
    if (const char* xdg = std::getenv("XDG_CONFIG_HOME"); xdg != nullptr && *xdg != '\0') {
        return std::filesystem::path{xdg} / "DivergenceSplitter";
    }
    return std::filesystem::path{std::getenv("HOME")} / ".config" / "DivergenceSplitter";
#endif
}

std::filesystem::path default_settings_path() {
    return application_data_directory() / "settings.json";
}

std::filesystem::path default_log_path() {
    return application_data_directory() / "diagnostics.log";
}

std::string current_timestamp() {
    const auto now = std::chrono::system_clock::now();
    const auto time = std::chrono::system_clock::to_time_t(now);
    std::tm local{};
#ifdef _WIN32
    localtime_s(&local, &time);
#else
    localtime_r(&time, &local);
#endif
    std::ostringstream stream;
    stream << std::put_time(&local, "%Y-%m-%dT%H:%M:%S");
    return stream.str();
}

}  // namespace divergencesplitter
