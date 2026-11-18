#include "file_dialog.hpp"

#include <shobjidl.h>
#include <wrl/client.h>

#include <stdexcept>
#include <string>
#include <vector>

namespace divergencesplitter::ui {
namespace {

using Microsoft::WRL::ComPtr;

[[noreturn]] void throw_dialog_error(const char* operation, HRESULT result) {
    throw std::runtime_error(
        std::string{operation} + " failed (HRESULT " + std::to_string(result) + ")"
    );
}

void apply_initial_location(
    IFileDialog* dialog,
    const std::optional<std::filesystem::path>& initial
) {
    if (!initial.has_value()) {
        return;
    }
    if (!initial->filename().empty()) {
        dialog->SetFileName(initial->filename().c_str());
    }
    if (initial->has_parent_path()) {
        ComPtr<IShellItem> folder;
        if (SUCCEEDED(SHCreateItemFromParsingName(
                initial->parent_path().c_str(),
                nullptr,
                IID_PPV_ARGS(&folder)
            ))) {
            dialog->SetFolder(folder.Get());
        }
    }
}

void apply_filters(IFileDialog* dialog, std::span<const FileDialogFilter> filters) {
    if (filters.empty()) {
        return;
    }
    std::vector<COMDLG_FILTERSPEC> specs;
    specs.reserve(filters.size());
    for (const auto& filter : filters) {
        specs.push_back(COMDLG_FILTERSPEC{filter.name, filter.pattern});
    }
    dialog->SetFileTypes(static_cast<UINT>(specs.size()), specs.data());
    dialog->SetFileTypeIndex(1);
}

std::optional<std::filesystem::path> result_path(IFileDialog* dialog) {
    ComPtr<IShellItem> item;
    if (FAILED(dialog->GetResult(&item))) {
        return std::nullopt;
    }
    PWSTR raw = nullptr;
    const HRESULT result = item->GetDisplayName(SIGDN_FILESYSPATH, &raw);
    if (FAILED(result)) {
        throw_dialog_error("GetDisplayName", result);
    }
    std::filesystem::path path{raw};
    CoTaskMemFree(raw);
    return path;
}

}  // namespace

std::optional<std::filesystem::path> open_file_dialog(
    HWND owner,
    const std::wstring& title,
    std::span<const FileDialogFilter> filters,
    const std::optional<std::filesystem::path>& initial
) {
    ComPtr<IFileOpenDialog> dialog;
    HRESULT result = CoCreateInstance(
        CLSID_FileOpenDialog,
        nullptr,
        CLSCTX_INPROC_SERVER,
        IID_PPV_ARGS(&dialog)
    );
    if (FAILED(result)) {
        throw_dialog_error("CoCreateInstance(FileOpenDialog)", result);
    }
    dialog->SetTitle(title.c_str());
    dialog->SetOptions(
        FOS_FORCEFILESYSTEM | FOS_FILEMUSTEXIST | FOS_PATHMUSTEXIST | FOS_NOCHANGEDIR
    );
    apply_filters(dialog.Get(), filters);
    apply_initial_location(dialog.Get(), initial);
    result = dialog->Show(owner);
    if (result == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
        return std::nullopt;
    }
    if (FAILED(result)) {
        throw_dialog_error("IFileOpenDialog::Show", result);
    }
    return result_path(dialog.Get());
}

std::optional<std::filesystem::path> save_file_dialog(
    HWND owner,
    const std::wstring& title,
    std::span<const FileDialogFilter> filters,
    const std::wstring& default_extension,
    const std::optional<std::filesystem::path>& initial
) {
    ComPtr<IFileSaveDialog> dialog;
    HRESULT result = CoCreateInstance(
        CLSID_FileSaveDialog,
        nullptr,
        CLSCTX_INPROC_SERVER,
        IID_PPV_ARGS(&dialog)
    );
    if (FAILED(result)) {
        throw_dialog_error("CoCreateInstance(FileSaveDialog)", result);
    }
    dialog->SetTitle(title.c_str());
    dialog->SetOptions(
        FOS_FORCEFILESYSTEM | FOS_PATHMUSTEXIST | FOS_OVERWRITEPROMPT | FOS_NOCHANGEDIR
    );
    apply_filters(dialog.Get(), filters);
    if (!default_extension.empty()) {
        dialog->SetDefaultExtension(default_extension.c_str());
    }
    apply_initial_location(dialog.Get(), initial);
    result = dialog->Show(owner);
    if (result == HRESULT_FROM_WIN32(ERROR_CANCELLED)) {
        return std::nullopt;
    }
    if (FAILED(result)) {
        throw_dialog_error("IFileSaveDialog::Show", result);
    }
    return result_path(dialog.Get());
}

}  // namespace divergencesplitter::ui
