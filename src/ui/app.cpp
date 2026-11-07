#include "app.hpp"

#include <imgui.h>
#include <imgui_impl_dx11.h>
#include <imgui_impl_win32.h>

#include <algorithm>
#include <cmath>
#include <iterator>
#include <stdexcept>

#include "about_page.hpp"
#include "divergencesplitter/capture/ndi.hpp"
#include "divergencesplitter/text.hpp"
#include "monitor_page.hpp"
#include "profile_page.hpp"
#include "settings_page.hpp"
#include "ui_helpers.hpp"

extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(
    HWND window,
    UINT message,
    WPARAM wparam,
    LPARAM lparam
);

namespace divergencesplitter::ui {
namespace {

constexpr wchar_t kWindowClass[] = L"DivergenceSplitterWindow";
constexpr wchar_t kWindowTitle[] = L"DivergenceSplitter";

constexpr FileDialogFilter kProfileFilters[] = {
    {L"Profile JSON", L"*.json"},
    {L"All files", L"*.*"},
};

std::optional<std::filesystem::path> font_candidates() {
    wchar_t windows_directory[MAX_PATH]{};
    const UINT length = GetWindowsDirectoryW(windows_directory, MAX_PATH);
    if (length == 0 || length >= MAX_PATH) {
        return std::nullopt;
    }
    const std::filesystem::path fonts{std::filesystem::path{windows_directory} / L"Fonts"};
    for (const auto* name : {
             L"YuGothR.ttc",
             L"YuGothM.ttc",
             L"meiryo.ttc",
             L"msgothic.ttc",
             L"msyh.ttc",
             L"segoeui.ttf",
         }) {
        const auto path = fonts / name;
        if (std::filesystem::exists(path)) {
            return path;
        }
    }
    return std::nullopt;
}

}  // namespace

App::App() {
    theme_mode_ = theme::mode_from_string(controller_.settings().theme);
    if (controller_.profile_path().has_value()) {
        document_.adopt_saved(controller_.profile(), *controller_.profile_path());
    } else {
        document_.draft = default_profile();
        document_.saved = document_.draft;
    }
}

App::~App() {
    destroy_imgui();
    destroy_device();
    destroy_window();
    controller_.stop();
}

int App::run(HINSTANCE instance, int show_command, bool smoke_test) {
    smoke_test_ = smoke_test;
    if (!create_window(instance, show_command)) {
        return 1;
    }
    if (!create_device()) {
        destroy_window();
        return 1;
    }
    create_imgui();
    monitor_ = std::make_unique<MonitorPage>(this);
    profile_ = std::make_unique<ProfilePage>(this);
    settings_ = std::make_unique<SettingsPage>(this);
    about_ = std::make_unique<AboutPage>();
    apply_theme(theme_mode_);
    load_fonts(dpi_scale_);

    ShowWindow(window_, smoke_test_ ? SW_SHOWNORMAL : show_command);
    UpdateWindow(window_);

    while (running_) {
        MSG message;
        while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
            if (message.message == WM_QUIT) {
                running_ = false;
            }
        }
        if (!running_) {
            break;
        }
        if (minimized_) {
            Sleep(10);
            continue;
        }
        frame();
    }

    about_.reset();
    settings_.reset();
    profile_.reset();
    monitor_.reset();
    if (smoke_test_ && exit_code_ == 0 && !smoke_test_ok()) {
        exit_code_ = 3;
    }
    destroy_imgui();
    destroy_device();
    destroy_window();
    return exit_code_;
}

bool App::create_window(HINSTANCE instance, int) {
    WNDCLASSEXW description{};
    description.cbSize = sizeof(description);
    description.style = CS_HREDRAW | CS_VREDRAW;
    description.lpfnWndProc = &App::window_proc;
    description.hInstance = instance;
    description.hCursor = LoadCursorW(nullptr, reinterpret_cast<LPCWSTR>(IDC_ARROW));
    description.lpszClassName = kWindowClass;
    if (RegisterClassExW(&description) == 0) {
        return false;
    }
    window_class_registered_ = true;
    window_ = CreateWindowExW(
        0,
        kWindowClass,
        kWindowTitle,
        WS_OVERLAPPEDWINDOW,
        CW_USEDEFAULT,
        CW_USEDEFAULT,
        1200,
        900,
        nullptr,
        nullptr,
        instance,
        this
    );
    if (window_ == nullptr) {
        return false;
    }
    dpi_scale_ = std::clamp(ImGui_ImplWin32_GetDpiScaleForHwnd(window_), 0.5f, 4.0f);
    return true;
}

void App::destroy_window() {
    if (window_ != nullptr) {
        DestroyWindow(window_);
        window_ = nullptr;
    }
    if (window_class_registered_) {
        UnregisterClassW(kWindowClass, GetModuleHandleW(nullptr));
        window_class_registered_ = false;
    }
}

LRESULT CALLBACK App::window_proc(
    HWND window,
    UINT message,
    WPARAM wparam,
    LPARAM lparam
) {
    App* app = reinterpret_cast<App*>(GetWindowLongPtrW(window, GWLP_USERDATA));
    if (message == WM_NCCREATE) {
        const auto* create = reinterpret_cast<CREATESTRUCTW*>(lparam);
        app = static_cast<App*>(create->lpCreateParams);
        SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(app));
    }
    if (app != nullptr) {
        return app->handle_message(window, message, wparam, lparam);
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

LRESULT App::handle_message(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    if (imgui_ != nullptr && ImGui_ImplWin32_WndProcHandler(window, message, wparam, lparam)) {
        return 1;
    }
    switch (message) {
        case WM_SIZE:
            minimized_ = wparam == SIZE_MINIMIZED;
            if (!minimized_ && swap_chain_ && wparam != SIZE_MINIMIZED) {
                const UINT width = LOWORD(lparam);
                const UINT height = HIWORD(lparam);
                if (width > 0 && height > 0) {
                    if (context_) {
                        context_->OMSetRenderTargets(0, nullptr, nullptr);
                    }
                    destroy_render_target();
                    const HRESULT result = swap_chain_->ResizeBuffers(
                        0,
                        width,
                        height,
                        DXGI_FORMAT_UNKNOWN,
                        0
                    );
                    if (FAILED(result) || !create_render_target()) {
                        running_ = false;
                    }
                }
            }
            return 0;
        case WM_DPICHANGED: {
            const auto* suggested = reinterpret_cast<const RECT*>(lparam);
            SetWindowPos(
                window,
                nullptr,
                suggested->left,
                suggested->top,
                suggested->right - suggested->left,
                suggested->bottom - suggested->top,
                SWP_NOZORDER | SWP_NOACTIVATE
            );
            dpi_pending_ = true;
            dpi_pending_scale_ = static_cast<float>(HIWORD(wparam)) / 96.0f;
            return 0;
        }
        case WM_GETMINMAXINFO: {
            auto* info = reinterpret_cast<MINMAXINFO*>(lparam);
            info->ptMinTrackSize.x = static_cast<LONG>(900.0f * dpi_scale_);
            info->ptMinTrackSize.y = static_cast<LONG>(600.0f * dpi_scale_);
            return 0;
        }
        case WM_ERASEBKGND:
            return 1;
        case WM_PAINT: {
            PAINTSTRUCT paint;
            BeginPaint(window, &paint);
            EndPaint(window, &paint);
            return 0;
        }
        case WM_CLOSE:
            if (!smoke_test_ && document_.dirty() &&
                !confirm(
                    "DivergenceSplitter",
                    "Discard the unsaved Profile changes?"
                )) {
                return 0;
            }
            DestroyWindow(window);
            return 0;
        case WM_DESTROY:
            running_ = false;
            PostQuitMessage(0);
            return 0;
        default:
            return DefWindowProcW(window, message, wparam, lparam);
    }
}

bool App::create_device() {
    DXGI_SWAP_CHAIN_DESC description{};
    description.BufferCount = 2;
    description.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
    description.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT;
    description.OutputWindow = window_;
    description.SampleDesc.Count = 1;
    description.Windowed = TRUE;
    description.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;

    UINT flags = 0;
#ifdef _DEBUG
    flags |= D3D11_CREATE_DEVICE_DEBUG;
#endif
    const D3D_FEATURE_LEVEL levels[] = {
        D3D_FEATURE_LEVEL_11_0,
        D3D_FEATURE_LEVEL_10_0,
    };
    const auto create = [&](D3D_DRIVER_TYPE driver) {
        return D3D11CreateDeviceAndSwapChain(
            nullptr,
            driver,
            nullptr,
            flags,
            levels,
            static_cast<UINT>(std::size(levels)),
            D3D11_SDK_VERSION,
            &description,
            &swap_chain_,
            &device_,
            nullptr,
            &context_
        );
    };
    HRESULT result = create(D3D_DRIVER_TYPE_HARDWARE);
    if (FAILED(result)) {
        flags &= ~D3D11_CREATE_DEVICE_DEBUG;
        result = create(D3D_DRIVER_TYPE_WARP);
    }
    if (FAILED(result)) {
        return false;
    }
    return create_render_target();
}

bool App::create_render_target() {
    Microsoft::WRL::ComPtr<ID3D11Texture2D> back_buffer;
    if (FAILED(swap_chain_->GetBuffer(0, IID_PPV_ARGS(&back_buffer)))) {
        return false;
    }
    return SUCCEEDED(device_->CreateRenderTargetView(
        back_buffer.Get(),
        nullptr,
        &render_target_
    ));
}

void App::destroy_render_target() {
    if (context_) {
        context_->OMSetRenderTargets(0, nullptr, nullptr);
    }
    render_target_.Reset();
}

void App::destroy_device() {
    if (context_) {
        context_->ClearState();
        context_->Flush();
    }
    destroy_render_target();
    swap_chain_.Reset();
    context_.Reset();
    device_.Reset();
}

void App::create_imgui() {
    IMGUI_CHECKVERSION();
    imgui_ = ImGui::CreateContext();
    ImGuiIO& io = ImGui::GetIO();
    io.IniFilename = nullptr;
    io.LogFilename = nullptr;
    io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
    ImGui_ImplWin32_Init(window_);
    ImGui_ImplDX11_Init(device_.Get(), context_.Get());
    imgui_initialized_ = true;
    imgui_dx11_initialized_ = true;
}

void App::destroy_imgui() {
    if (imgui_dx11_initialized_) {
        ImGui_ImplDX11_Shutdown();
        imgui_dx11_initialized_ = false;
    }
    if (imgui_initialized_) {
        ImGui_ImplWin32_Shutdown();
        imgui_initialized_ = false;
    }
    if (imgui_ != nullptr) {
        ImGui::DestroyContext(imgui_);
        imgui_ = nullptr;
    }
}

void App::load_fonts(float scale) {
    ImGuiIO& io = ImGui::GetIO();
    io.Fonts->Clear();
    const auto font_path = font_candidates();
    ImFont* font = nullptr;
    if (font_path.has_value()) {
        ImFontConfig config;
        config.OversampleH = 2;
        config.OversampleV = 2;
        config.PixelSnapH = true;
        config.FontNo = 0;
        const std::string path = path_to_utf8(*font_path);
        font = io.Fonts->AddFontFromFileTTF(
            path.c_str(),
            16.0f * scale,
            &config,
            io.Fonts->GetGlyphRangesJapanese()
        );
    }
    if (font == nullptr) {
        font = io.Fonts->AddFontDefault();
    }
    io.FontDefault = font;
    ImGui_ImplDX11_InvalidateDeviceObjects();
    ImGui_ImplDX11_CreateDeviceObjects();
}

void App::apply_theme(theme::Mode mode) {
    theme_mode_ = mode;
    theme::apply(mode, dpi_scale_);
    ImGui::GetIO().FontGlobalScale = 1.0f;
}

void App::apply_pending_dpi() {
    if (!dpi_pending_) {
        return;
    }
    dpi_pending_ = false;
    dpi_scale_ = std::clamp(dpi_pending_scale_, 0.5f, 4.0f);
    apply_theme(theme_mode_);
    load_fonts(dpi_scale_);
}

void App::frame() {
    apply_pending_dpi();
    ImGui_ImplDX11_NewFrame();
    ImGui_ImplWin32_NewFrame();
    ImGui::NewFrame();
    tick(ImGui::GetTime());
    draw();
    ImGui::Render();
    if (!render_target_) {
        return;
    }

    const auto palette = theme::colors(theme_mode_);
    const float clear_color[4] = {
        palette.background.x,
        palette.background.y,
        palette.background.z,
        1.0f,
    };
    context_->OMSetRenderTargets(1, render_target_.GetAddressOf(), nullptr);
    context_->ClearRenderTargetView(render_target_.Get(), clear_color);
    ImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());
    swap_chain_->Present(1, 0);
}

void App::tick(double now) {
    if (page_ == AppPage::monitor && monitor_) {
        monitor_->update(now);
    }
    if (profile_) {
        profile_->update(page_ == AppPage::profile, now);
    }
    if (!toast_message_.empty() && now >= toast_until_) {
        toast_message_.clear();
        toast_error_ = false;
    }
    if (smoke_test_ && ++smoke_frames_ >= 20) {
        exit_code_ = smoke_test_ok() ? 0 : 3;
        running_ = false;
    }
}

void App::draw() {
    if (smoke_test_) {
        page_ = smoke_frames_ < 10 ? AppPage::monitor : AppPage::about;
    }
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(viewport->WorkPos);
    ImGui::SetNextWindowSize(viewport->WorkSize);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(0.0f, 0.0f));
    ImGui::PushStyleVar(ImGuiStyleVar_WindowRounding, 0.0f);
    ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
    const ImGuiWindowFlags flags =
        ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove |
        ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoSavedSettings |
        ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoNavFocus;
    ImGui::Begin("##root", nullptr, flags);
    ImGui::PopStyleVar(3);

    draw_navigation();

    ImGui::SameLine(0.0f, 0.0f);
    ImGui::BeginChild("##content", ImVec2(0.0f, 0.0f), false);
    switch (page_) {
        case AppPage::monitor:
            if (monitor_) monitor_->draw();
            break;
        case AppPage::profile:
            if (profile_) profile_->draw();
            break;
        case AppPage::settings:
            if (settings_) settings_->draw();
            break;
        case AppPage::about:
            if (about_) about_->draw();
            break;
    }
    ImGui::EndChild();
    ImGui::End();

    draw_toast();
}

void App::draw_navigation() {
    const auto palette = theme::colors(theme_mode_);
    ImGui::PushStyleColor(ImGuiCol_ChildBg, palette.surface_low);
    ImGui::BeginChild("##navigation", ImVec2(190.0f * dpi_scale_, 0.0f), true);
    ImGui::PopStyleColor();

    ImGui::PushStyleColor(ImGuiCol_Text, palette.text);
    ImGui::TextUnformatted("DivergenceSplitter");
    ImGui::PopStyleColor();
    ImGui::Spacing();
    ImGui::Separator();
    ImGui::Spacing();

    const auto item = [&](const char* label, AppPage target) {
        if (ImGui::Selectable(label, page_ == target, 0, ImVec2(0.0f, 38.0f * dpi_scale_))) {
            page_ = target;
        }
    };
    item("Monitor", AppPage::monitor);
    item("Profile", AppPage::profile);
    item("Settings", AppPage::settings);
    item("About", AppPage::about);

    ImGui::Dummy(ImVec2(0.0f, 12.0f));
    ImGui::Separator();
    ImGui::Dummy(ImVec2(0.0f, 6.0f));
    text_muted("Version " DIVERGENCESPLITTER_VERSION);
    ImGui::EndChild();
}

void App::draw_toast() {
    if (toast_message_.empty()) {
        return;
    }
    const ImGuiViewport* viewport = ImGui::GetMainViewport();
    const ImVec2 position(
        viewport->WorkPos.x + viewport->WorkSize.x * 0.5f,
        viewport->WorkPos.y + viewport->WorkSize.y - 24.0f
    );
    ImGui::SetNextWindowPos(position, ImGuiCond_Always, ImVec2(0.5f, 1.0f));
    ImGui::SetNextWindowBgAlpha(0.96f);
    const ImGuiWindowFlags flags =
        ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_AlwaysAutoResize |
        ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoFocusOnAppearing |
        ImGuiWindowFlags_NoNav | ImGuiWindowFlags_NoMove;
    ImGui::Begin("##toast", nullptr, flags);
    const auto palette = theme::colors(theme_mode_);
    ImGui::PushStyleColor(
        ImGuiCol_Text,
        toast_error_ ? palette.error : palette.text
    );
    ImGui::PushTextWrapPos(ImGui::GetFontSize() * 32.0f);
    ImGui::TextUnformatted(toast_message_.c_str());
    ImGui::PopTextWrapPos();
    ImGui::PopStyleColor();
    ImGui::End();
}

void App::notify(std::string message, bool error) {
    if (message.empty()) {
        return;
    }
    toast_message_ = std::move(message);
    toast_error_ = error;
    toast_until_ = ImGui::GetCurrentContext() != nullptr ? ImGui::GetTime() + 3.5 : 0.0;
}

void App::show_error(const std::string& title, const std::string& message) {
    const std::wstring wide_title = to_wide(title);
    const std::wstring wide_message = to_wide(message);
    MessageBoxW(
        window_,
        wide_message.c_str(),
        wide_title.c_str(),
        MB_OK | MB_ICONERROR | MB_SETFOREGROUND
    );
}

bool App::confirm(const std::string& title, const std::string& message) {
    const std::wstring wide_title = to_wide(title);
    const std::wstring wide_message = to_wide(message);
    return MessageBoxW(
               window_,
               wide_message.c_str(),
               wide_title.c_str(),
               MB_YESNO | MB_ICONQUESTION | MB_SETFOREGROUND
           ) == IDYES;
}

std::optional<std::filesystem::path> App::pick_open_file(
    const std::wstring& title,
    std::span<const FileDialogFilter> filters,
    const std::optional<std::filesystem::path>& initial
) {
    try {
        return open_file_dialog(window_, title, filters, initial);
    } catch (const std::exception& error) {
        notify(std::string{"File dialog failed: "} + error.what(), true);
        return std::nullopt;
    }
}

std::optional<std::filesystem::path> App::pick_save_file(
    const std::wstring& title,
    std::span<const FileDialogFilter> filters,
    const std::wstring& default_extension,
    const std::optional<std::filesystem::path>& initial
) {
    try {
        return save_file_dialog(window_, title, filters, default_extension, initial);
    } catch (const std::exception& error) {
        notify(std::string{"File dialog failed: "} + error.what(), true);
        return std::nullopt;
    }
}

void App::new_profile() {
    if (!confirm_discard("New Profile")) {
        return;
    }
    const auto initial = document_.path.has_value()
        ? std::optional<std::filesystem::path>{document_.path->parent_path() / L"profile.json"}
        : std::optional<std::filesystem::path>{std::filesystem::path{L"profile.json"}};
    const auto path = pick_save_file(
        L"New Profile",
        kProfileFilters,
        L"json",
        initial
    );
    if (!path.has_value()) {
        return;
    }
    document_.start_new(*path);
    if (profile_) {
        profile_->load_draft(document_.draft);
    }
    notify("New profile; save to apply it.");
}

void App::open_profile() {
    if (!confirm_discard("Open Profile")) {
        return;
    }
    const auto path = pick_open_file(L"Open Profile", kProfileFilters, document_.path);
    if (!path.has_value()) {
        return;
    }
    if (profile_) {
        profile_->suspend_preview();
    }
    std::string error;
    if (!controller_.open_profile(*path, &error)) {
        notify(error, true);
        show_error("Open Profile", error);
        if (profile_) {
            profile_->resume_preview();
        }
        return;
    }
    document_.adopt_saved(controller_.profile(), *controller_.profile_path());
    if (profile_) {
        profile_->load_draft(document_.draft);
        profile_->resume_preview();
    }
    if (settings_) {
        settings_->reload();
    }
    apply_theme(theme::mode_from_string(controller_.settings().theme));
    notify("Profile opened.");
}

bool App::save_profile_to(const std::filesystem::path& path) {
    std::string error;
    if (!controller_.save_profile_file(path, document_.draft, &error)) {
        notify(error, true);
        show_error("Save Profile", error);
        return false;
    }
    document_.mark_saved(document_.draft, path);
    notify("Profile saved.");
    return true;
}

void App::save_profile() {
    if (!document_.path.has_value()) {
        save_profile_as();
        return;
    }
    (void)save_profile_to(*document_.path);
}

void App::save_profile_as() {
    const auto initial = document_.path.has_value()
        ? std::optional<std::filesystem::path>{*document_.path}
        : std::optional<std::filesystem::path>{std::filesystem::path{L"profile.json"}};
    const auto path = pick_save_file(L"Save Profile As", kProfileFilters, L"json", initial);
    if (!path.has_value()) {
        return;
    }
    (void)save_profile_to(*path);
}

bool App::confirm_discard(const std::string& title) {
    return !document_.dirty() ||
           confirm(title, "Discard the unsaved Profile changes?");
}

bool App::smoke_test_ok() {
    if (!IsWindow(window_) || !IsWindowVisible(window_)) {
        return false;
    }
    try {
        if (ndi_enabled()) {
            (void)acquire_ndi_runtime();
        }
    } catch (const std::exception&) {
        return false;
    }
    return true;
}

}  // namespace divergencesplitter::ui
