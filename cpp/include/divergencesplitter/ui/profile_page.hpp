#pragma once

#include <QWidget>

#include <vector>
#include <functional>

#include "divergencesplitter/capture/camera_devices.hpp"
#include "divergencesplitter/configuration/configuration.hpp"

class QCheckBox;
class QComboBox;
class QDoubleSpinBox;
class QLabel;
class QLineEdit;
class QPushButton;
class QSpinBox;
class QStackedWidget;
class QTableWidget;
class QThread;

namespace divergencesplitter::ui {

class AppController;

class ProfilePage final : public QWidget {
    Q_OBJECT

public:
    using NdiDiscovery = std::function<std::vector<std::string>()>;
    explicit ProfilePage(AppController* controller, QWidget* parent = nullptr, NdiDiscovery ndi_discovery = {});
    ~ProfilePage() override;

    void reload_from_controller();
    [[nodiscard]] Profile draft_profile() const;

signals:
    void profileApplied();
    void statusMessage(const QString& message);

private:
    void load_profile(const Profile& profile);
    void apply();
    void add_instance();
    void remove_instance();
    void browse_scenario();
    void browse_video();
    void source_type_changed(int index);
    void update_source_stack();
    void refresh_ndi_sources();
    void refresh_camera_devices();
    void populate_camera_devices(
        const std::optional<CameraDeviceConfiguration>& device,
        const std::optional<CameraModeConfiguration>& mode
    );
    void populate_camera_modes(
        const std::vector<CameraModeInfo>& modes,
        const std::optional<CameraModeConfiguration>& configured
    );
    void camera_device_changed(int index);
    void camera_mode_changed(int index);

    AppController* controller_;

    QComboBox* source_type_;
    QStackedWidget* source_stack_;

    QSpinBox* camera_index_;
    QComboBox* camera_backend_;
    QComboBox* camera_device_combo_;
    QComboBox* camera_mode_combo_;
    QPushButton* camera_detect_button_;
    QLineEdit* camera_name_;
    QLineEdit* camera_subtype_;
    QLabel* camera_note_;
    std::vector<CameraDeviceInfo> camera_devices_;
    std::vector<CameraModeInfo> camera_modes_;
    QSpinBox* camera_width_;
    QSpinBox* camera_height_;
    QDoubleSpinBox* camera_fps_;
    QCheckBox* camera_request_60_;

    QLineEdit* video_path_;

    QComboBox* ndi_name_;
    QLabel* ndi_notice_;
    QPushButton* ndi_refresh_;
    QThread* ndi_worker_{};
    NdiDiscovery ndi_discovery_;
    bool ndi_discovery_available_{};

    QCheckBox* crop_enabled_;
    QSpinBox* crop_left_;
    QSpinBox* crop_right_;
    QSpinBox* crop_top_;
    QSpinBox* crop_bottom_;

    QCheckBox* resize_enabled_;
    QCheckBox* resize_references_;
    QSpinBox* resize_width_;
    QSpinBox* resize_height_;
    QComboBox* resize_interpolation_;

    QTableWidget* instance_table_;
    QLabel* status_label_;
};

}  // namespace divergencesplitter::ui
