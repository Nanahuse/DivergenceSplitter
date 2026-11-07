#pragma once

#include <filesystem>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace divergencesplitter::ui {

struct LicenseComponent {
    std::string name;
    std::string license;
    std::string license_file;
    std::string url;
    std::string source;
};

struct LicenseInventory {
    std::string application_license;
    std::string application_license_file;
    std::vector<LicenseComponent> components;
};

[[nodiscard]] std::filesystem::path application_directory();
[[nodiscard]] std::optional<LicenseInventory> load_license_inventory();
[[nodiscard]] std::vector<std::string> transitive_license_files();
[[nodiscard]] bool open_file(std::string_view relative_path);

}  // namespace divergencesplitter::ui
