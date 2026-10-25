#pragma once

#include <QWidget>

#include <vector>

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

namespace divergencesplitter::ui {

class AppController;

class ProfilePage final : public QWidget {
    Q_OBJECT

public:
    explicit ProfilePage(AppController* controller, QWidget* parent = nullptr);

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

    AppController* controller_;

    QComboBox* source_type_;
    QStackedWidget* source_stack_;

    QSpinBox* camera_index_;
    QComboBox* camera_backend_;
    QSpinBox* camera_width_;
    QSpinBox* camera_height_;
    QDoubleSpinBox* camera_fps_;
    QCheckBox* camera_request_60_;

    QLineEdit* video_path_;

    QLineEdit* ndi_name_;
    QLabel* ndi_notice_;

    QCheckBox* crop_enabled_;
    QSpinBox* crop_left_;
    QSpinBox* crop_right_;
    QSpinBox* crop_top_;
    QSpinBox* crop_bottom_;

    QCheckBox* resize_enabled_;
    QSpinBox* resize_width_;
    QSpinBox* resize_height_;
    QComboBox* resize_interpolation_;

    QTableWidget* instance_table_;
    QLabel* status_label_;
};

}  // namespace divergencesplitter::ui
