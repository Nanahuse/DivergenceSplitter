#include <Windows.h>
#include <shellapi.h>

#include <imgui_impl_win32.h>

#include <string>

#include "app.hpp"

int WINAPI WinMain(HINSTANCE instance, HINSTANCE, LPSTR, int show_command) {
    int argument_count = 0;
    LPWSTR* arguments = CommandLineToArgvW(GetCommandLineW(), &argument_count);
    bool smoke_test = false;
    for (int index = 1; index < argument_count; ++index) {
        if (std::wstring{arguments[index]} == L"--smoke-test") {
            smoke_test = true;
        }
    }
    if (arguments != nullptr) {
        LocalFree(arguments);
    }

    const HRESULT com = CoInitializeEx(
        nullptr,
        COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE
    );
    if (FAILED(com)) {
        MessageBoxW(
            nullptr,
            L"COM initialization failed.",
            L"DivergenceSplitter",
            MB_OK | MB_ICONERROR
        );
        return 1;
    }

    ImGui_ImplWin32_EnableDpiAwareness();
    int result = 0;
    {
        divergencesplitter::ui::App app;
        result = app.run(instance, show_command, smoke_test);
    }
    CoUninitialize();
    return result;
}
