#pragma once

#include <Windows.h>

#include <d3d11.h>
#include <wrl/client.h>

#include <filesystem>
#include <memory>
#include <optional>
#include <span>
#include <string>

#include "divergencesplitter/configuration/configuration.hpp"

#include "app_controller.hpp"
#include "file_dialog.hpp"
#include "profile_document.hpp"
#include "theme.hpp"

struct ImGuiContext;

namespace divergencesplitter::ui {

enum class AppPage {
    monitor,
    profile,
    settings,
    about,
};

class MonitorPage;
class ProfilePage;
class SettingsPage;
class AboutPage;

class App final {
public:
    App();
    ~App();

    App(const App&) = delete;
    App& operator=(const App&) = delete;

    int run(HINSTANCE instance, int show_command, bool smoke_test);

    [[nodiscard]] HWND window() const noexcept { return window_; }
    [[nodiscard]] ID3D11Device* device() const noexcept { return device_.Get(); }
    [[nodiscard]] ID3D11DeviceContext* context() const noexcept { return context_.Get(); }
    [[nodiscard]] AppController& controller() noexcept { return controller_; }
    [[nodiscard]] const AppController& controller() const noexcept { return controller_; }
    [[nodiscard]] ProfileDocument& document() noexcept { return document_; }
    [[nodiscard]] const ProfileDocument& document() const noexcept { return document_; }
    [[nodiscard]] theme::Mode theme_mode() const noexcept { return theme_mode_; }
    [[nodiscard]] float dpi_scale() const noexcept { return dpi_scale_; }

    void notify(std::string message, bool error = false);
    void show_error(const std::string& title, const std::string& message);
    [[nodiscard]] bool confirm(const std::string& title, const std::string& message);

    [[nodiscard]] std::optional<std::filesystem::path> pick_open_file(
        const std::wstring& title,
        std::span<const FileDialogFilter> filters,
        const std::optional<std::filesystem::path>& initial = std::nullopt
    );
    [[nodiscard]] std::optional<std::filesystem::path> pick_save_file(
        const std::wstring& title,
        std::span<const FileDialogFilter> filters,
        const std::wstring& default_extension,
        const std::optional<std::filesystem::path>& initial = std::nullopt
    );

    void apply_theme(theme::Mode mode);
    void new_profile();
    void open_profile();
    void save_profile();
    void save_profile_as();

private:
    static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam);
    LRESULT handle_message(HWND window, UINT message, WPARAM wparam, LPARAM lparam);

    bool create_window(HINSTANCE instance, int show_command);
    void destroy_window();
    bool create_device();
    void destroy_device();
    bool create_render_target();
    void destroy_render_target();
    void create_imgui();
    void destroy_imgui();
    void load_fonts(float scale);
    void frame();
    void draw();
    void draw_navigation();
    void draw_toast();
    void tick(double now);
    void apply_pending_dpi();

    bool save_profile_to(const std::filesystem::path& path);
    [[nodiscard]] bool confirm_discard(const std::string& title);
    [[nodiscard]] bool smoke_test_ok();

    HWND window_{};
    bool window_class_registered_{};
    Microsoft::WRL::ComPtr<ID3D11Device> device_;
    Microsoft::WRL::ComPtr<ID3D11DeviceContext> context_;
    Microsoft::WRL::ComPtr<IDXGISwapChain> swap_chain_;
    Microsoft::WRL::ComPtr<ID3D11RenderTargetView> render_target_;
    ImGuiContext* imgui_{};
    bool imgui_initialized_{};
    bool imgui_dx11_initialized_{};

    AppController controller_;
    ProfileDocument document_;
    std::unique_ptr<MonitorPage> monitor_;
    std::unique_ptr<ProfilePage> profile_;
    std::unique_ptr<SettingsPage> settings_;
    std::unique_ptr<AboutPage> about_;
    AppPage page_{AppPage::monitor};
    theme::Mode theme_mode_{theme::Mode::light};
    float dpi_scale_{1.0f};
    bool dpi_pending_{};
    float dpi_pending_scale_{1.0f};

    std::string toast_message_;
    bool toast_error_{};
    double toast_until_{};

    bool smoke_test_{};
    int smoke_frames_{};
    int exit_code_{};
    bool running_{true};
    bool minimized_{};
};

}  // namespace divergencesplitter::ui
