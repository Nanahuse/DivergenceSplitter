#include <windows.h>
#include <shellapi.h>

#include <filesystem>
#include <string>
#include <string_view>

#include "webview_host.hpp"

namespace {

std::filesystem::path command_line_document() {
    int count = 0;
    LPWSTR* arguments = CommandLineToArgvW(GetCommandLineW(), &count);
    if (arguments == nullptr) {
        return {};
    }
    std::filesystem::path result;
    for (int index = 1; index + 1 < count; ++index) {
        if (std::wstring_view{arguments[index]} == L"--open") {
            result = arguments[index + 1];
            break;
        }
    }
    LocalFree(arguments);
    return result;
}

}  // namespace

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    return divergencesplitter::scenario_builder::run_scenario_builder(command_line_document());
}
