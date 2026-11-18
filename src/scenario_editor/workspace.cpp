#include "divergencesplitter/scenario/editor/workspace.hpp"

#include <opencv2/imgcodecs.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <fstream>
#include <set>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

#include "divergencesplitter/scenario/editor/document.hpp"

namespace divergencesplitter::scenario_editor {
namespace {

constexpr std::size_t max_asset_name_attempts = 4096;

std::string lower_extension(const std::filesystem::path& path) {
    std::string extension = path.extension().string();
    std::transform(extension.begin(), extension.end(), extension.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    return extension;
}

bool supported_image(const std::filesystem::path& path) {
    static const std::set<std::string> extensions{
        ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".ppm", ".pgm",
    };
    return extensions.contains(lower_extension(path));
}


std::vector<unsigned char> read_file(const std::filesystem::path& path) {
    std::ifstream stream{path, std::ios::binary};
    if (!stream) {
        throw ScenarioEditorError("could not open file: " + path_to_utf8(path));
    }
    std::vector<unsigned char> bytes{
        std::istreambuf_iterator<char>{stream},
        std::istreambuf_iterator<char>{},
    };
    if (stream.bad()) {
        throw ScenarioEditorError("could not read file: " + path_to_utf8(path));
    }
    return bytes;
}

std::filesystem::path unique_import_temp(const std::filesystem::path& asset_directory) {
    static std::atomic<std::size_t> sequence{0};
    const auto unique = std::chrono::steady_clock::now().time_since_epoch().count();
    return asset_directory
        / (".import-" + std::to_string(unique) + "-" + std::to_string(++sequence) + ".tmp");
}

}  // namespace

void ScenarioWorkspace::open(const std::filesystem::path& directory) {
    if (directory.empty()) {
        throw ScenarioEditorError("workspace directory must not be empty");
    }
    std::error_code error;
    const auto absolute = std::filesystem::absolute(directory, error);
    if (error) {
        throw ScenarioEditorError("could not resolve workspace directory");
    }
    if (!std::filesystem::is_directory(absolute, error) || error) {
        throw ScenarioEditorError(
            "workspace directory was not found: " + path_to_utf8(absolute)
        );
    }
    root_ = std::filesystem::weakly_canonical(absolute, error);
    if (error) {
        throw ScenarioEditorError("could not canonicalize workspace directory");
    }

    const auto assets = root_ / "Asset";
    if (std::filesystem::exists(assets, error)) {
        if (error || !std::filesystem::is_directory(assets, error) || error
            || !contains(assets)) {
            throw ScenarioEditorError("Asset must be a directory inside the workspace");
        }
    } else {
        if (!std::filesystem::create_directory(assets, error) || error) {
            throw ScenarioEditorError("could not create the workspace Asset directory");
        }
    }
}

std::filesystem::path ScenarioWorkspace::asset_directory() const {
    if (!is_open()) {
        throw ScenarioEditorError("workspace is not open");
    }
    const auto path = root_ / "Asset";
    if (!contains(path)) {
        throw ScenarioEditorError("Asset directory leaves the workspace");
    }
    return path;
}

std::vector<std::filesystem::path> ScenarioWorkspace::list_scenarios() const {
    if (!is_open()) {
        throw ScenarioEditorError("workspace is not open");
    }
    std::vector<std::filesystem::path> result;
    std::error_code error;
    for (const auto& entry : std::filesystem::directory_iterator{root_, error}) {
        if (error) {
            throw ScenarioEditorError("could not list workspace scenarios");
        }
        const auto status = entry.symlink_status(error);
        if (error || !std::filesystem::is_regular_file(status)) {
            continue;
        }
        const auto extension = lower_extension(entry.path());
        if (extension == ".yaml" || extension == ".yml") {
            result.push_back(entry.path().filename());
        }
    }
    std::sort(result.begin(), result.end());
    return result;
}

std::vector<std::string> ScenarioWorkspace::list_assets() const {
    if (!is_open()) {
        throw ScenarioEditorError("workspace is not open");
    }
    std::vector<std::string> result;
    std::error_code error;
    for (const auto& entry : std::filesystem::directory_iterator{asset_directory(), error}) {
        if (error) {
            throw ScenarioEditorError("could not list workspace assets");
        }
        const auto status = entry.symlink_status(error);
        if (error || !std::filesystem::is_regular_file(status) || !supported_image(entry.path())) {
            continue;
        }
        result.push_back(asset_reference(path_to_utf8(entry.path().filename())));
    }
    std::sort(result.begin(), result.end());
    return result;
}

std::filesystem::path ScenarioWorkspace::scenario_path(std::string_view filename) const {
    if (!is_open()) {
        throw ScenarioEditorError("workspace is not open");
    }
    if (filename.empty()) {
        throw ScenarioEditorError("scenario file name must not be empty");
    }
    const auto name = path_from_utf8(filename);
    if (name.has_parent_path() || name.is_absolute() || name.has_root_name()
        || name.has_root_directory() || name.filename() != name || name == "." || name == "..") {
        throw ScenarioEditorError("scenario file must be directly inside the workspace");
    }
    const auto extension = lower_extension(name);
    if (extension != ".yaml" && extension != ".yml") {
        throw ScenarioEditorError("scenario file must use .yaml or .yml");
    }
    const auto candidate = root_ / name;
    std::error_code error;
    const bool exists = std::filesystem::exists(candidate, error);
    if (error) {
        throw ScenarioEditorError("could not check scenario path");
    }
    if (exists) {
        error.clear();
        if (std::filesystem::is_symlink(candidate, error)) {
            throw ScenarioEditorError("scenario symlinks are not supported");
        }
        if (error) {
            throw ScenarioEditorError("could not check scenario path");
        }
    }
    if (!contains(candidate)) {
        throw ScenarioEditorError("scenario path leaves the workspace");
    }
    return candidate;
}

void ScenarioWorkspace::validate_scenario_destination(
    const std::filesystem::path& path
) const {
    if (!is_open()) {
        throw ScenarioEditorError("workspace is not open");
    }
    std::error_code error;
    const auto absolute = std::filesystem::absolute(path, error);
    if (error) {
        throw ScenarioEditorError("could not resolve scenario path");
    }
    const auto parent = std::filesystem::weakly_canonical(absolute.parent_path(), error);
    if (error || parent != root_) {
        throw ScenarioEditorError("scenario file must be saved directly in the workspace");
    }
    (void)scenario_path(path_to_utf8(absolute.filename()));
}

std::string ScenarioWorkspace::import_asset(const std::filesystem::path& source) {
    if (!is_open()) {
        throw ScenarioEditorError("workspace is not open");
    }
    std::error_code error;
    if (!std::filesystem::is_regular_file(source, error) || error) {
        throw ScenarioEditorError("image file was not found: " + path_to_utf8(source));
    }
    if (!supported_image(source)) {
        throw ScenarioEditorError("unsupported image extension: " + path_to_utf8(source));
    }

    const auto bytes = read_file(source);
    if (bytes.empty()) {
        throw ScenarioEditorError("image file is empty: " + path_to_utf8(source));
    }
    const auto temp = unique_import_temp(asset_directory());
    try {
        {
            std::ofstream stream{temp, std::ios::binary | std::ios::trunc};
            if (!stream) {
                throw ScenarioEditorError("could not create a temporary Asset file");
            }
            stream.write(
                reinterpret_cast<const char*>(bytes.data()),
                static_cast<std::streamsize>(bytes.size())
            );
            stream.flush();
            if (!stream) {
                throw ScenarioEditorError("could not write a temporary Asset file");
            }
        }
        const auto stored = read_file(temp);
        if (stored.empty() || cv::imdecode(stored, cv::IMREAD_UNCHANGED).empty()) {
            throw ScenarioEditorError(
                "selected file is not a readable image: " + path_to_utf8(source)
            );
        }

        const std::filesystem::path source_name = source.filename();
        const auto stem = source_name.stem();
        const auto extension = source_name.extension();
        std::filesystem::path candidate = source_name;
        for (std::size_t attempt = 1; attempt <= max_asset_name_attempts; ++attempt) {
            if (attempt > 1) {
                candidate = stem;
                candidate += "_" + std::to_string(attempt);
                candidate += extension;
            }
            const auto destination = asset_directory() / candidate;
            if (std::filesystem::exists(destination, error)) {
                if (error) {
                    throw ScenarioEditorError("could not check Asset destination");
                }
                continue;
            }
            error.clear();
            std::filesystem::rename(temp, destination, error);
            if (!error) {
                return asset_reference(path_to_utf8(candidate));
            }
            if (std::filesystem::exists(destination, error)) {
                continue;
            }
            throw ScenarioEditorError(
                "could not copy image into Asset: " + path_to_utf8(source)
            );
        }
        throw ScenarioEditorError("could not choose a unique Asset file name");
    } catch (...) {
        std::error_code ignored;
        std::filesystem::remove(temp, ignored);
        throw;
    }
}

std::string ScenarioWorkspace::asset_reference(std::string_view filename) {
    if (filename.empty() || filename.find('/') != std::string_view::npos
        || filename.find('\\') != std::string_view::npos) {
        throw ScenarioEditorError("Asset file name must not contain a path");
    }
    return "Asset/" + std::string{filename};
}

void ScenarioWorkspace::validate_asset_reference(std::string_view reference) {
    if (reference.empty() || reference.find('\\') != std::string_view::npos) {
        throw ScenarioEditorError("asset references must use forward slashes");
    }
    const auto path = path_from_utf8(reference);
    if (path.is_absolute() || path.has_root_name() || path.has_root_directory()) {
        throw ScenarioEditorError("asset references must be relative");
    }
    std::vector<std::string> parts;
    std::size_t start = 0;
    while (start <= reference.size()) {
        const auto end = reference.find('/', start);
        const auto part = reference.substr(
            start,
            end == std::string_view::npos ? std::string_view::npos : end - start
        );
        if (part.empty() || part == "." || part == "..") {
            throw ScenarioEditorError("invalid asset reference: " + std::string{reference});
        }
        parts.emplace_back(part);
        if (end == std::string_view::npos) {
            break;
        }
        start = end + 1;
    }
    if (parts.size() != 2 || parts[0] != "Asset"
        || !supported_image(path_from_utf8(parts[1]))) {
        throw ScenarioEditorError(
            "asset reference must be Asset/<image>: " + std::string{reference}
        );
    }
}

std::filesystem::path ScenarioWorkspace::resolve_asset_reference(
    std::string_view reference
) const {
    if (!is_open()) {
        throw ScenarioEditorError("workspace is not open");
    }
    validate_asset_reference(reference);
    const auto path = root_ / path_from_utf8(reference);
    if (!contains(path)) {
        throw ScenarioEditorError("asset reference leaves the workspace");
    }
    return path;
}

bool ScenarioWorkspace::contains(const std::filesystem::path& path) const {
    std::error_code error;
    const auto canonical = std::filesystem::weakly_canonical(path, error);
    if (error) {
        return false;
    }
    const auto relative = std::filesystem::relative(canonical, root_, error);
    if (error || relative.is_absolute()) {
        return false;
    }
    const auto first = relative.begin();
    return first == relative.end() || *first != "..";
}

}  // namespace divergencesplitter::scenario_editor
