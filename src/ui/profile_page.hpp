#pragma once

#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "divergencesplitter/capture/camera_devices.hpp"
#include "divergencesplitter/configuration/configuration.hpp"
#include "image_texture.hpp"
#include "ndi_discovery.hpp"
#include "profile_preview.hpp"

namespace divergencesplitter::ui {

class App;

class ProfilePage {
public:
    using NdiDiscovery = std::function<std::vector<std::string>()>;

    explicit ProfilePage(App* app, NdiDiscovery ndi_discovery = {});
    ~ProfilePage();

    ProfilePage(const ProfilePage&) = delete;
    ProfilePage& operator=(const ProfilePage&) = delete;

    void update(bool visible, double now);
    void draw();
    void load_draft(const Profile& profile);
    void reload_draft();
    void suspend_preview();
    void resume_preview();
    [[nodiscard]] Profile draft_profile() const;

private:
    void draw_toolbar();
    void draw_input_tab();
    void draw_source_controls();
    void draw_camera_source();
    void draw_video_source();
    void draw_ndi_source();
    void draw_transform_controls();
    void draw_preview();
    void draw_scenarios_tab();
    void draw_actions();
    void apply();

    void switch_source(int type);
    void refresh_preview();
    void stop_preview();
    void ensure_camera_devices();
    void refresh_camera_devices();
    void populate_camera_modes(
        const std::vector<CameraModeInfo>& modes,
        const std::optional<CameraModeConfiguration>& configured
    );
    void select_camera_device(int index);
    void select_camera_mode(int index);
    void refresh_ndi_sources();
    void poll_ndi_discovery();
    void browse_scenario(std::size_t index);
    void browse_video();

    App* app_;
    ProfilePreview preview_worker_;
    ImageTexture preview_texture_;
    bool preview_enabled_{true};
    bool preview_suspended_{};
    std::string preview_status_;
    double next_preview_{};
    bool visible_{};

    std::vector<CameraDeviceInfo> camera_devices_;
    std::vector<CameraModeInfo> camera_modes_;
    bool camera_devices_loaded_{};
    std::string camera_note_;

    NdiDiscovery ndi_discovery_;
    bool ndi_discovery_available_{};
    std::vector<std::string> ndi_sources_;
    std::string ndi_notice_;
    double ndi_last_search_{};
    NdiDiscoveryWorker ndi_worker_;

    std::string status_;
};

}  // namespace divergencesplitter::ui
