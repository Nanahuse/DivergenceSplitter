#include <windows.h>
#include <shellapi.h>

#include <filesystem>
#include <string>
#include <string_view>

#include "divergencesplitter/scenario/editor/document.hpp"
#include "webview_host.hpp"

namespace {

struct CommandLine {
    std::filesystem::path document;
    std::filesystem::path check;
};

CommandLine parse_command_line() {
    int count = 0;
    LPWSTR* arguments = CommandLineToArgvW(GetCommandLineW(), &count);
    if (arguments == nullptr) {
        return {};
    }
    CommandLine result;
    for (int index = 1; index + 1 < count; ++index) {
        const std::wstring_view argument{arguments[index]};
        if (argument == L"--open") {
            result.document = arguments[index + 1];
            ++index;
        } else if (argument == L"--check") {
            result.check = arguments[index + 1];
            ++index;
        }
    }
    LocalFree(arguments);
    return result;
}

int check_document(const std::filesystem::path& path) {
    try {
        const auto document = divergencesplitter::scenario_editor::load_scenario_document(path);
        (void)divergencesplitter::scenario_editor::export_scenario_yaml(document);
        return 0;
    } catch (const std::exception&) {
        return 1;
    }
}

}  // namespace

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    const CommandLine arguments = parse_command_line();
    if (!arguments.check.empty()) {
        return check_document(arguments.check);
    }
    return divergencesplitter::scenario_builder::run_scenario_builder(arguments.document);
}
