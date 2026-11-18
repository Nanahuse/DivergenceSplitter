#include "license_inventory.hpp"

#include <Windows.h>
#include <shellapi.h>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <fstream>
#include <vector>

#include "divergencesplitter/text.hpp"

namespace divergencesplitter::ui {

std::filesystem::path application_directory() {
    std::vector<wchar_t> buffer(32768);
    const DWORD length = GetModuleFileNameW(
        nullptr,
        buffer.data(),
        static_cast<DWORD>(buffer.size())
    );
    if (length == 0 || length >= buffer.size()) {
        return std::filesystem::current_path();
    }
    return std::filesystem::path{std::wstring{buffer.data(), length}}.parent_path();
}

std::optional<LicenseInventory> load_license_inventory() {
    std::ifstream stream{application_directory() / "licenses" / "components.json"};
    if (!stream) {
        return std::nullopt;
    }
    try {
        const auto document = nlohmann::json::parse(stream);
        LicenseInventory inventory;
        const auto& application = document.at("application");
        inventory.application_license = application.at("license").get<std::string>();
        inventory.application_license_file =
            application.at("license_file").get<std::string>();
        for (const auto& entry : document.at("components")) {
            LicenseComponent component;
            component.name = entry.at("name").get<std::string>();
            component.license = entry.at("license").get<std::string>();
            component.license_file = entry.value("license_file", std::string{});
            component.url = entry.value("url", std::string{});
            component.source = entry.value("source", std::string{});
            inventory.components.push_back(std::move(component));
        }
        return inventory;
    } catch (const std::exception&) {
        return std::nullopt;
    }
}

std::vector<std::string> license_notice_files(const LicenseInventory* inventory) {
    std::vector<std::string> result;
    const auto directory = application_directory() / "licenses" / "vcpkg";
    std::error_code error;
    if (!std::filesystem::is_directory(directory, error)) {
        return result;
    }
    for (const auto& entry : std::filesystem::directory_iterator(directory, error)) {
        if (!entry.is_regular_file() || entry.path().extension() != ".txt") {
            continue;
        }
        const std::string name = entry.path().stem().string();
        bool direct = false;
        if (inventory != nullptr) {
            for (const auto& component : inventory->components) {
                if (component.source.starts_with("vcpkg:") &&
                    component.source.substr(6) == name) {
                    direct = true;
                    break;
                }
            }
        }
        if (!direct) {
            result.push_back("licenses/vcpkg/" + entry.path().filename().string());
        }
    }
    std::sort(result.begin(), result.end());
    return result;
}

bool open_file(std::string_view relative_path) {
    const auto path = application_directory() / path_from_utf8(relative_path);
    if (!std::filesystem::is_regular_file(path)) {
        return false;
    }
    return reinterpret_cast<INT_PTR>(ShellExecuteW(
               nullptr,
               L"open",
               path.c_str(),
               nullptr,
               nullptr,
               SW_SHOWNORMAL
           )) > 32;
}

}  // namespace divergencesplitter::ui
