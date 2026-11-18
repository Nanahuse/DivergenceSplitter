#pragma once

#include <filesystem>
#include <string>
#include <string_view>
#include <vector>

namespace divergencesplitter::scenario_editor {

class ScenarioWorkspace {
public:
    void open(const std::filesystem::path& directory);

    [[nodiscard]] bool is_open() const noexcept { return !root_.empty(); }
    [[nodiscard]] const std::filesystem::path& root() const noexcept { return root_; }
    [[nodiscard]] std::filesystem::path asset_directory() const;

    [[nodiscard]] std::vector<std::filesystem::path> list_scenarios() const;
    [[nodiscard]] std::vector<std::string> list_assets() const;

    [[nodiscard]] std::filesystem::path scenario_path(std::string_view filename) const;
    void validate_scenario_destination(const std::filesystem::path& path) const;

    // Copies an image into Asset and returns its YAML reference, for example
    // "Asset/DPC.png". Existing files are never overwritten.
    [[nodiscard]] std::string import_asset(const std::filesystem::path& source);

    [[nodiscard]] static std::string asset_reference(std::string_view filename);
    static void validate_asset_reference(std::string_view reference);
    [[nodiscard]] std::filesystem::path resolve_asset_reference(
        std::string_view reference
    ) const;

private:
    [[nodiscard]] bool contains(const std::filesystem::path& path) const;

    std::filesystem::path root_;
};

}  // namespace divergencesplitter::scenario_editor
