#include "webview_host.hpp"

#include <windows.h>
#include <commdlg.h>
#include <shlobj.h>
#include <wrl.h>

#include <WebView2.h>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <string_view>

#include "divergencesplitter/scenario/editor/document.hpp"

namespace divergencesplitter::scenario_builder {
namespace {

using Microsoft::WRL::Callback;
using Microsoft::WRL::ComPtr;
using nlohmann::json;
using scenario_editor::EditorSession;
using scenario_editor::apply_editor_command;
using scenario_editor::editor_state_json;
using scenario_editor::new_editor_session;
using scenario_editor::open_editor_session;
using scenario_editor::save_editor_session;

constexpr wchar_t window_class[] = L"DivergenceSplitterScenarioBuilder";

std::wstring to_wide(std::string_view text) {
    if (text.empty()) {
        return {};
    }
    const int length = MultiByteToWideChar(
        CP_UTF8, MB_ERR_INVALID_CHARS, text.data(), static_cast<int>(text.size()), nullptr, 0
    );
    if (length <= 0) {
        return L"invalid UTF-8";
    }
    std::wstring result(static_cast<std::size_t>(length), L'\0');
    MultiByteToWideChar(
        CP_UTF8,
        MB_ERR_INVALID_CHARS,
        text.data(),
        static_cast<int>(text.size()),
        result.data(),
        length
    );
    return result;
}

std::string to_utf8(std::wstring_view text) {
    if (text.empty()) {
        return {};
    }
    const int length = WideCharToMultiByte(
        CP_UTF8, 0, text.data(), static_cast<int>(text.size()), nullptr, 0, nullptr, nullptr
    );
    if (length <= 0) {
        return {};
    }
    std::string result(static_cast<std::size_t>(length), '\0');
    WideCharToMultiByte(
        CP_UTF8,
        0,
        text.data(),
        static_cast<int>(text.size()),
        result.data(),
        length,
        nullptr,
        nullptr
    );
    return result;
}

std::filesystem::path executable_directory() {
    std::wstring buffer(32768, L'\0');
    const DWORD length = GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (length == 0 || length >= buffer.size()) {
        throw std::runtime_error("could not locate the Scenario Builder executable");
    }
    buffer.resize(length);
    return std::filesystem::path{buffer}.parent_path();
}

std::filesystem::path local_app_data() {
    PWSTR raw = nullptr;
    if (FAILED(SHGetKnownFolderPath(FOLDERID_LocalAppData, KF_FLAG_DEFAULT, nullptr, &raw))) {
        throw std::runtime_error("could not locate LOCALAPPDATA for the WebView2 profile");
    }
    std::filesystem::path result{raw};
    CoTaskMemFree(raw);
    return result;
}

std::filesystem::path pick_open_file(HWND owner) {
    std::wstring buffer(32768, L'\0');
    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = owner;
    dialog.lpstrFilter = L"Scenario YAML (*.yaml;*.yml)\0*.yaml;*.yml\0All files (*.*)\0*.*\0";
    dialog.lpstrFile = buffer.data();
    dialog.nMaxFile = static_cast<DWORD>(buffer.size());
    dialog.Flags = OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR;
    if (!GetOpenFileNameW(&dialog)) {
        return {};
    }
    return std::filesystem::path{buffer.c_str()};
}

std::filesystem::path pick_save_file(HWND owner, const std::filesystem::path& current) {
    std::wstring buffer(32768, L'\0');
    const std::wstring suggested = current.empty()
        ? std::wstring{L"scenario.yaml"}
        : current.filename().wstring();
    if (suggested.size() < buffer.size()) {
        std::copy(suggested.begin(), suggested.end(), buffer.begin());
    }

    OPENFILENAMEW dialog{};
    dialog.lStructSize = sizeof(dialog);
    dialog.hwndOwner = owner;
    dialog.lpstrFilter = L"Scenario YAML (*.yaml;*.yml)\0*.yaml;*.yml\0All files (*.*)\0*.*\0";
    dialog.lpstrFile = buffer.data();
    dialog.nMaxFile = static_cast<DWORD>(buffer.size());
    dialog.lpstrDefExt = L"yaml";
    dialog.Flags = OFN_PATHMUSTEXIST | OFN_OVERWRITEPROMPT | OFN_NOCHANGEDIR;
    if (!GetSaveFileNameW(&dialog)) {
        return {};
    }
    return std::filesystem::path{buffer.c_str()};
}

class WebViewHost {
public:
    explicit WebViewHost(std::filesystem::path initial_document)
        : initial_document_(std::move(initial_document)) {}

    int run() {
        const HRESULT com_result = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
        const bool com_initialized = SUCCEEDED(com_result);
        if (FAILED(com_result) && com_result != RPC_E_CHANGED_MODE) {
            MessageBoxW(nullptr, L"COM initialization failed.", L"Scenario Builder", MB_ICONERROR);
            return 1;
        }

        if (!initial_document_.empty()) {
            try {
                session_ = open_editor_session(initial_document_);
            } catch (const std::exception& error) {
                const std::wstring message = to_wide(error.what());
                MessageBoxW(
                    nullptr,
                    message.c_str(),
                    L"Scenario Builder",
                    MB_ICONWARNING
                );
                session_ = new_editor_session();
            }
        } else {
            session_ = new_editor_session();
        }

        create_window();
        initialize_webview();

        MSG message{};
        while (GetMessageW(&message, nullptr, 0, 0) > 0) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }

        webview_.Reset();
        controller_.Reset();
        if (com_initialized) {
            CoUninitialize();
        }
        return 0;
    }

private:
    static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
        WebViewHost* self = reinterpret_cast<WebViewHost*>(
            GetWindowLongPtrW(window, GWLP_USERDATA)
        );
        if (message == WM_NCCREATE) {
            const auto* create = reinterpret_cast<CREATESTRUCTW*>(lparam);
            self = static_cast<WebViewHost*>(create->lpCreateParams);
            SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        }
        if (self == nullptr) {
            return DefWindowProcW(window, message, wparam, lparam);
        }
        switch (message) {
        case WM_SIZE:
            if (self->controller_) {
                RECT bounds{};
                GetClientRect(window, &bounds);
                self->controller_->put_Bounds(bounds);
            }
            return 0;
        case WM_SETFOCUS:
            if (self->controller_) {
                self->controller_->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
            }
            return 0;
        case WM_CLOSE:
            if (!self->confirm_discard_changes()) {
                return 0;
            }
            DestroyWindow(window);
            return 0;
        case WM_DESTROY:
            PostQuitMessage(0);
            return 0;
        default:
            return DefWindowProcW(window, message, wparam, lparam);
        }
    }

    void create_window() {
        WNDCLASSEXW window_class_info{};
        window_class_info.cbSize = sizeof(window_class_info);
        window_class_info.lpfnWndProc = window_proc;
        window_class_info.hInstance = GetModuleHandleW(nullptr);
        window_class_info.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        window_class_info.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_WINDOW + 1);
        window_class_info.lpszClassName = window_class;
        if (!RegisterClassExW(&window_class_info)) {
            throw std::runtime_error("could not register the Scenario Builder window");
        }
        window_ = CreateWindowExW(
            0,
            window_class,
            L"DivergenceSplitter Scenario Builder",
            WS_OVERLAPPEDWINDOW,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            1280,
            860,
            nullptr,
            nullptr,
            GetModuleHandleW(nullptr),
            this
        );
        if (window_ == nullptr) {
            throw std::runtime_error("could not create the Scenario Builder window");
        }
        update_title();
        ShowWindow(window_, SW_SHOW);
        UpdateWindow(window_);
    }

    void initialize_webview() {
        const auto user_data = local_app_data() / "DivergenceSplitter" / "ScenarioBuilder";
        std::error_code error;
        std::filesystem::create_directories(user_data, error);
        if (error) {
            throw std::runtime_error("could not create the WebView2 user data directory");
        }

        auto environment_handler =
            Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
                [this](HRESULT result, ICoreWebView2Environment* environment) -> HRESULT {
                    if (FAILED(result) || environment == nullptr) {
                        webview_failed(L"WebView2 environment initialization failed.");
                        return result;
                    }
                    auto controller_handler =
                        Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                            [this](
                                HRESULT controller_result,
                                ICoreWebView2Controller* controller
                            ) -> HRESULT {
                                if (FAILED(controller_result) || controller == nullptr) {
                                    webview_failed(
                                        L"WebView2 controller initialization failed."
                                    );
                                    return controller_result;
                                }
                                controller_ = controller;
                                initialize_controller();
                                return S_OK;
                            }
                        );
                    environment->CreateCoreWebView2Controller(
                        window_, controller_handler.Get()
                    );
                    return S_OK;
                }
            );
        const HRESULT result = CreateCoreWebView2EnvironmentWithOptions(
            nullptr,
            user_data.c_str(),
            nullptr,
            environment_handler.Get()
        );
        if (FAILED(result)) {
            throw std::runtime_error(
                "WebView2 Runtime is unavailable. Install the Microsoft Edge WebView2 Runtime."
            );
        }
    }

    void initialize_controller() {
        try {
            RECT bounds{};
            GetClientRect(window_, &bounds);
            controller_->put_Bounds(bounds);
            controller_->put_IsVisible(TRUE);
            controller_->MoveFocus(COREWEBVIEW2_MOVE_FOCUS_REASON_PROGRAMMATIC);
            controller_->get_CoreWebView2(webview_.ReleaseAndGetAddressOf());

            auto message_handler = Callback<ICoreWebView2WebMessageReceivedEventHandler>(
                [this](ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs* args) -> HRESULT {
                    LPWSTR source_raw = nullptr;
                    if (FAILED(args->get_Source(&source_raw)) || source_raw == nullptr) {
                        return S_OK;
                    }
                    const std::wstring source = source_raw;
                    CoTaskMemFree(source_raw);
                    if (source.rfind(L"https://app.local/", 0) != 0
                        && source != L"https://app.local") {
                        return S_OK;
                    }

                    LPWSTR raw = nullptr;
                    if (FAILED(args->get_WebMessageAsJson(&raw)) || raw == nullptr) {
                        return S_OK;
                    }
                    const std::string text = to_utf8(raw);
                    CoTaskMemFree(raw);
                    handle_message(text);
                    return S_OK;
                }
            );
            webview_->add_WebMessageReceived(message_handler.Get(), nullptr);

            auto navigation_handler = Callback<ICoreWebView2NavigationStartingEventHandler>(
                [](ICoreWebView2*, ICoreWebView2NavigationStartingEventArgs* args) -> HRESULT {
                    LPWSTR uri_raw = nullptr;
                    if (FAILED(args->get_Uri(&uri_raw)) || uri_raw == nullptr) {
                        return S_OK;
                    }
                    const std::wstring uri = uri_raw;
                    CoTaskMemFree(uri_raw);
                    if (uri.rfind(L"https://app.local/", 0) != 0
                        && uri != L"https://app.local") {
                        args->put_Cancel(TRUE);
                    }
                    return S_OK;
                }
            );
            webview_->add_NavigationStarting(navigation_handler.Get(), nullptr);

            auto new_window_handler = Callback<ICoreWebView2NewWindowRequestedEventHandler>(
                [](ICoreWebView2*, ICoreWebView2NewWindowRequestedEventArgs* args) -> HRESULT {
                    args->put_Handled(TRUE);
                    return S_OK;
                }
            );
            webview_->add_NewWindowRequested(new_window_handler.Get(), nullptr);

            const auto ui = executable_directory() / "scenario-builder-ui";
            if (!std::filesystem::exists(ui / "index.html")) {
                throw std::runtime_error(
                    "scenario-builder-ui/index.html was not found next to the executable"
                );
            }
            ComPtr<ICoreWebView2_3> webview3;
            if (FAILED(webview_.As(&webview3))) {
                throw std::runtime_error(
                    "the installed WebView2 Runtime does not support virtual host mapping"
                );
            }
            webview3->SetVirtualHostNameToFolderMapping(
                L"app.local",
                ui.c_str(),
                COREWEBVIEW2_HOST_RESOURCE_ACCESS_KIND_DENY_CORS
            );
            webview_->Navigate(L"https://app.local/index.html");
        } catch (const std::exception& error) {
            const std::wstring message = to_wide(error.what());
            webview_failed(message.c_str());
        }
    }

    void webview_failed(const wchar_t* message) {
        MessageBoxW(window_, message, L"Scenario Builder", MB_ICONERROR);
        PostQuitMessage(1);
    }

    void handle_message(const std::string& text) {
        try {
            const json message = json::parse(text);
            const std::string type = message.value("type", "");
            if (type == "ready") {
                publish_state();
                return;
            }
            if (type == "command") {
                apply_editor_command(session_, message.at("command"));
                update_title();
                publish_state();
                return;
            }
            if (type == "new") {
                if (!confirm_discard_changes()) {
                    return;
                }
                session_ = new_editor_session();
                update_title();
                publish_state();
                return;
            }
            if (type == "open") {
                if (!confirm_discard_changes()) {
                    return;
                }
                const auto path = pick_open_file(window_);
                if (!path.empty()) {
                    session_ = open_editor_session(path);
                    update_title();
                    publish_state();
                }
                return;
            }
            if (type == "save" || type == "saveAs") {
                (void)save(type == "saveAs");
                return;
            }
        } catch (const std::exception& error) {
            publish_error(error.what());
        }
    }

    bool confirm_discard_changes() {
        if (!session_.dirty) {
            return true;
        }
        const int answer = MessageBoxW(
            window_,
            L"保存されていない変更があります。保存しますか？",
            L"Scenario Builder",
            MB_YESNOCANCEL | MB_ICONWARNING
        );
        if (answer == IDCANCEL) {
            return false;
        }
        if (answer == IDYES) {
            try {
                return save(false);
            } catch (const std::exception& error) {
                const std::wstring message = to_wide(error.what());
                MessageBoxW(window_, message.c_str(), L"Scenario Builder", MB_ICONERROR);
                return false;
            }
        }
        return true;
    }

    bool save(bool force_picker) {
        std::filesystem::path path = session_.path;
        if (force_picker || path.empty()) {
            path = pick_save_file(window_, path);
        }
        if (path.empty()) {
            return false;
        }
        save_editor_session(session_, path);
        update_title();
        publish_state();
        return true;
    }

    void update_title() {
        const std::wstring name = session_.path.empty()
            ? L"Untitled"
            : session_.path.filename().wstring();
        const std::wstring dirty = session_.dirty ? L" *" : L"";
        SetWindowTextW(window_, (L"Scenario Builder - " + name + dirty).c_str());
    }

    void publish_state() {
        if (!webview_) {
            return;
        }
        try {
            json state = editor_state_json(session_);
            state["type"] = "state";
            const std::wstring serialized = to_wide(state.dump());
            webview_->PostWebMessageAsJson(serialized.c_str());
        } catch (const std::exception& error) {
            publish_error(error.what());
        }
    }

    void publish_error(const std::string& message) {
        if (!webview_) {
            return;
        }
        const json failure{{"type", "error"}, {"message", message}};
        const std::wstring serialized = to_wide(failure.dump());
        webview_->PostWebMessageAsJson(serialized.c_str());
    }

    std::filesystem::path initial_document_;
    EditorSession session_;
    HWND window_{};
    ComPtr<ICoreWebView2Controller> controller_;
    ComPtr<ICoreWebView2> webview_;
};

}  // namespace

int run_scenario_builder(const std::filesystem::path& initial_document) {
    try {
        WebViewHost host{initial_document};
        return host.run();
    } catch (const std::exception& error) {
        const std::wstring message = to_wide(error.what());
        MessageBoxW(
            nullptr,
            message.c_str(),
            L"Scenario Builder",
            MB_ICONERROR
        );
        return 1;
    }
}

}  // namespace divergencesplitter::scenario_builder
