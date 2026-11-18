#pragma once

#include <Windows.h>

#include <filesystem>
#include <optional>
#include <span>
#include <string>

namespace divergencesplitter::ui {

struct FileDialogFilter {
    const wchar_t* name;
    const wchar_t* pattern;
};

[[nodiscard]] std::optional<std::filesystem::path> open_file_dialog(
    HWND owner,
    const std::wstring& title,
    std::span<const FileDialogFilter> filters,
    const std::optional<std::filesystem::path>& initial = std::nullopt
);

[[nodiscard]] std::optional<std::filesystem::path> save_file_dialog(
    HWND owner,
    const std::wstring& title,
    std::span<const FileDialogFilter> filters,
    const std::wstring& default_extension,
    const std::optional<std::filesystem::path>& initial = std::nullopt
);

}  // namespace divergencesplitter::ui
