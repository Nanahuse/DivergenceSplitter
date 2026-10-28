#include "divergencesplitter/ui/profile_page.hpp"

#include <QCheckBox>
#include <QComboBox>
#include <QDoubleSpinBox>
#include <QFileDialog>
#include <QFormLayout>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QScrollArea>
#include <QSignalBlocker>
#include <QSpinBox>
#include <QStackedWidget>
#include <QTableWidget>
#include <QTableWidgetItem>
#include <QVBoxLayout>

#include <algorithm>

#include <filesystem>
#include <variant>

#include "divergencesplitter/scenario/scenario.hpp"
#include "divergencesplitter/ui/app_controller.hpp"

namespace divergencesplitter::ui {
namespace {

QString path_text(const std::string& path) {
    return QString::fromStdString(path);
}

std::string to_std(const QString& text) {
    return text.toStdString();
}

}  // namespace

ProfilePage::ProfilePage(AppController* controller, QWidget* parent)
    : QWidget(parent), controller_(controller) {
    auto* outer = new QVBoxLayout(this);
    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    auto* content = new QWidget(scroll);
    auto* layout = new QVBoxLayout(content);
    scroll->setWidget(content);
    outer->addWidget(scroll);

    auto* title = new QLabel(tr("Profile"), content);
    QFont title_font = title->font();
    title_font.setPointSize(title_font.pointSize() + 4);
    title_font.setBold(true);
    title->setFont(title_font);
    layout->addWidget(title);

    auto* draft_label = new QLabel(
        tr("Edits are kept as a draft. Apply restarts the runtime with the draft values."),
        content
    );
    draft_label->setWordWrap(true);
    layout->addWidget(draft_label);

    auto* source_group = new QGroupBox(tr("Input source"), content);
    auto* source_layout = new QVBoxLayout(source_group);
    source_type_ = new QComboBox(source_group);
    source_type_->addItems({tr("Camera"), tr("Video file"), tr("NDI")});
    source_layout->addWidget(source_type_);

    source_stack_ = new QStackedWidget(source_group);

    auto* camera_page = new QWidget(source_stack_);
    auto* camera_form = new QFormLayout(camera_page);
    camera_device_combo_ = new QComboBox(camera_page);
    camera_device_combo_->setMinimumWidth(260);
    camera_mode_combo_ = new QComboBox(camera_page);
    camera_detect_button_ = new QPushButton(tr("Detect cameras"), camera_page);
    camera_name_ = new QLineEdit(camera_page);
    camera_subtype_ = new QLineEdit(camera_page);
    camera_note_ = new QLabel(camera_page);
    camera_note_->setWordWrap(true);
    camera_index_ = new QSpinBox(camera_page);
    camera_index_->setRange(0, 64);
    camera_backend_ = new QComboBox(camera_page);
    camera_backend_->addItem(tr("Media Foundation"), QStringLiteral("media_foundation"));
    camera_backend_->addItem(tr("DirectShow"), QStringLiteral("direct_show"));
    camera_width_ = new QSpinBox(camera_page);
    camera_width_->setRange(1, 16384);
    camera_width_->setValue(1920);
    camera_height_ = new QSpinBox(camera_page);
    camera_height_->setRange(1, 16384);
    camera_height_->setValue(1080);
    camera_fps_ = new QDoubleSpinBox(camera_page);
    camera_fps_->setRange(0.1, 240.0);
    camera_fps_->setValue(60.0);
    camera_request_60_ = new QCheckBox(tr("Request 60 fps"), camera_page);
    auto* device_row = new QHBoxLayout;
    device_row->addWidget(camera_device_combo_, 1);
    device_row->addWidget(camera_detect_button_);
    camera_form->addRow(tr("Device"), device_row);
    camera_form->addRow(tr("Device name"), camera_name_);
    camera_form->addRow(tr("Mode"), camera_mode_combo_);
    camera_form->addRow(tr("Backend"), camera_backend_);
    camera_form->addRow(tr("Device index"), camera_index_);
    camera_form->addRow(tr("Width"), camera_width_);
    camera_form->addRow(tr("Height"), camera_height_);
    camera_form->addRow(tr("FPS"), camera_fps_);
    camera_form->addRow(tr("Subtype GUID"), camera_subtype_);
    camera_form->addRow(camera_request_60_);
    camera_form->addRow(camera_note_);
    source_stack_->addWidget(camera_page);

    auto* video_page = new QWidget(source_stack_);
    auto* video_layout = new QHBoxLayout(video_page);
    video_path_ = new QLineEdit(video_page);
    auto* video_browse = new QPushButton(tr("Browse..."), video_page);
    video_layout->addWidget(video_path_, 1);
    video_layout->addWidget(video_browse);
    source_stack_->addWidget(video_page);

    auto* ndi_page = new QWidget(source_stack_);
    auto* ndi_layout = new QVBoxLayout(ndi_page);
    ndi_name_ = new QLineEdit(ndi_page);
    ndi_name_->setPlaceholderText(tr("NDI source name"));
    ndi_notice_ = new QLabel(
        tr("NDI input requires a build with the NDI SDK. Name matching is used instead of a "
           "discovery index."),
        ndi_page
    );
    ndi_notice_->setWordWrap(true);
    ndi_layout->addWidget(ndi_name_);
    ndi_layout->addWidget(ndi_notice_);
    source_stack_->addWidget(ndi_page);

    source_layout->addWidget(source_stack_);
    layout->addWidget(source_group);

    auto* transform_group = new QGroupBox(tr("Frame transform"), content);
    auto* transform_layout = new QVBoxLayout(transform_group);
    auto* crop_row = new QHBoxLayout;
    crop_enabled_ = new QCheckBox(tr("Crop margins"), transform_group);
    crop_left_ = new QSpinBox(transform_group);
    crop_right_ = new QSpinBox(transform_group);
    crop_top_ = new QSpinBox(transform_group);
    crop_bottom_ = new QSpinBox(transform_group);
    for (auto* spin : {crop_left_, crop_right_, crop_top_, crop_bottom_}) {
        spin->setRange(0, 16384);
        spin->setPrefix(tr("px "));
    }
    crop_row->addWidget(crop_enabled_);
    crop_row->addWidget(new QLabel(tr("L"), transform_group));
    crop_row->addWidget(crop_left_);
    crop_row->addWidget(new QLabel(tr("R"), transform_group));
    crop_row->addWidget(crop_right_);
    crop_row->addWidget(new QLabel(tr("T"), transform_group));
    crop_row->addWidget(crop_top_);
    crop_row->addWidget(new QLabel(tr("B"), transform_group));
    crop_row->addWidget(crop_bottom_);
    crop_row->addStretch(1);
    transform_layout->addLayout(crop_row);

    auto* resize_row = new QHBoxLayout;
    resize_enabled_ = new QCheckBox(tr("Resize"), transform_group);
    resize_enabled_->setObjectName(QStringLiteral("resizeEnabled"));
    resize_width_ = new QSpinBox(transform_group);
    resize_width_->setRange(1, 16384);
    resize_width_->setValue(1280);
    resize_height_ = new QSpinBox(transform_group);
    resize_height_->setRange(1, 16384);
    resize_height_->setValue(720);
    resize_interpolation_ = new QComboBox(transform_group);
    resize_interpolation_->addItems(
        {QStringLiteral("area"), QStringLiteral("nearest"), QStringLiteral("linear"),
         QStringLiteral("cubic"), QStringLiteral("lanczos4")}
    );
    resize_row->addWidget(resize_enabled_);
    resize_row->addWidget(new QLabel(tr("W"), transform_group));
    resize_row->addWidget(resize_width_);
    resize_row->addWidget(new QLabel(tr("H"), transform_group));
    resize_row->addWidget(resize_height_);
    resize_row->addWidget(new QLabel(tr("Interpolation"), transform_group));
    resize_row->addWidget(resize_interpolation_);
    resize_row->addStretch(1);
    transform_layout->addLayout(resize_row);
    resize_references_ = new QCheckBox(tr("Resize reference images"), transform_group);
    resize_references_->setObjectName(QStringLiteral("resizeReferences"));
    resize_references_->setEnabled(false);
    connect(resize_enabled_, &QCheckBox::toggled, resize_references_, &QWidget::setEnabled);
    transform_layout->addWidget(resize_references_);
    layout->addWidget(transform_group);

    auto* instances_group = new QGroupBox(tr("LiveSplit instances"), content);
    auto* instances_layout = new QVBoxLayout(instances_group);
    instance_table_ = new QTableWidget(instances_group);
    instance_table_->setColumnCount(2);
    instance_table_->setHorizontalHeaderLabels({tr("Bridge port"), tr("Scenario YAML")});
    instance_table_->horizontalHeader()->setStretchLastSection(true);
    instance_table_->verticalHeader()->setVisible(false);
    instance_table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    instances_layout->addWidget(instance_table_);
    auto* instance_buttons = new QHBoxLayout;
    auto* add_button = new QPushButton(tr("Add instance"), instances_group);
    auto* remove_button = new QPushButton(tr("Remove instance"), instances_group);
    auto* browse_button = new QPushButton(tr("Browse scenario..."), instances_group);
    instance_buttons->addWidget(add_button);
    instance_buttons->addWidget(remove_button);
    instance_buttons->addWidget(browse_button);
    instance_buttons->addStretch(1);
    instances_layout->addLayout(instance_buttons);
    layout->addWidget(instances_group, 1);

    status_label_ = new QLabel(tr("No profile applied."), content);
    status_label_->setWordWrap(true);
    layout->addWidget(status_label_);

    auto* actions = new QHBoxLayout;
    auto* reload_button = new QPushButton(tr("Revert draft"), content);
    auto* apply_button = new QPushButton(tr("Apply"), content);
    apply_button->setDefault(true);
    actions->addWidget(reload_button);
    actions->addStretch(1);
    actions->addWidget(apply_button);
    layout->addLayout(actions);

    connect(source_type_, &QComboBox::currentIndexChanged, this, &ProfilePage::source_type_changed);
    connect(camera_detect_button_, &QPushButton::clicked, this, [this]() {
        refresh_camera_devices();
    });
    connect(camera_device_combo_, &QComboBox::currentIndexChanged, this, &ProfilePage::camera_device_changed);
    connect(camera_mode_combo_, &QComboBox::currentIndexChanged, this, &ProfilePage::camera_mode_changed);
    connect(video_browse, &QPushButton::clicked, this, &ProfilePage::browse_video);
    connect(add_button, &QPushButton::clicked, this, &ProfilePage::add_instance);
    connect(remove_button, &QPushButton::clicked, this, &ProfilePage::remove_instance);
    connect(browse_button, &QPushButton::clicked, this, &ProfilePage::browse_scenario);
    connect(apply_button, &QPushButton::clicked, this, &ProfilePage::apply);
    connect(reload_button, &QPushButton::clicked, this, &ProfilePage::reload_from_controller);

    update_source_stack();
    reload_from_controller();
}

void ProfilePage::reload_from_controller() {
    load_profile(controller_->profile());
    status_label_->setText(tr("Draft loaded from the active profile."));
}

void ProfilePage::load_profile(const Profile& profile) {
    std::visit(
        [this](const auto& source) {
            using Source = std::decay_t<decltype(source)>;
            if constexpr (std::is_same_v<Source, CameraSourceConfiguration>) {
                source_type_->setCurrentIndex(0);
                camera_index_->setValue(source.device.index);
                const int backend_index = camera_backend_->findData(
                    QString::fromStdString(std::string{to_string(source.device.backend)})
                );
                camera_backend_->setCurrentIndex(std::max(0, backend_index));
                camera_name_->setText(QString::fromStdString(source.device.name));
                camera_subtype_->setText(QString::fromStdString(source.mode.subtype_guid));
                camera_width_->setValue(source.mode.width);
                camera_height_->setValue(source.mode.height);
                camera_fps_->setValue(source.mode.fps);
                camera_request_60_->setChecked(source.request_60_fps);
                populate_camera_devices(source.device, source.mode);
            } else if constexpr (std::is_same_v<Source, VideoSourceConfiguration>) {
                source_type_->setCurrentIndex(1);
                video_path_->setText(path_text(source.path));
            } else {
                source_type_->setCurrentIndex(2);
                ndi_name_->setText(path_text(source.name));
            }
            const auto& transform = source.transform;
            crop_enabled_->setChecked(transform.crop.has_value());
            crop_left_->setValue(transform.crop ? transform.crop->left : 0);
            crop_right_->setValue(transform.crop ? transform.crop->right : 0);
            crop_top_->setValue(transform.crop ? transform.crop->top : 0);
            crop_bottom_->setValue(transform.crop ? transform.crop->bottom : 0);
            resize_enabled_->setChecked(transform.resize.has_value());
            resize_references_->setChecked(
                transform.resize && transform.resize->resize_references
            );
            resize_width_->setValue(transform.resize ? transform.resize->width : 1280);
            resize_height_->setValue(transform.resize ? transform.resize->height : 720);
            if (transform.resize.has_value()) {
                const int index = resize_interpolation_->findText(
                    QString::fromStdString(std::string{to_string(transform.resize->interpolation)})
                );
                resize_interpolation_->setCurrentIndex(std::max(0, index));
            }
        },
        profile.source
    );
    update_source_stack();

    instance_table_->setRowCount(static_cast<int>(profile.instances.size()));
    for (int row = 0; row < static_cast<int>(profile.instances.size()); ++row) {
        const auto& instance = profile.instances[static_cast<std::size_t>(row)];
        auto* port_item = new QTableWidgetItem(QString::number(instance.connection.port));
        auto* scenario_item = new QTableWidgetItem(path_text(instance.scenario));
        instance_table_->setItem(row, 0, port_item);
        instance_table_->setItem(row, 1, scenario_item);
    }
}

Profile ProfilePage::draft_profile() const {
    Profile result;
    result.version = 2;

    TransformConfiguration transform;
    if (crop_enabled_->isChecked()) {
        transform.crop = CropConfiguration{
            crop_left_->value(),
            crop_right_->value(),
            crop_top_->value(),
            crop_bottom_->value(),
        };
    }
    if (resize_enabled_->isChecked()) {
        ResizeConfiguration resize;
        resize.width = resize_width_->value();
        resize.height = resize_height_->value();
        resize.resize_references = resize_references_->isChecked();
        resize.interpolation = parse_interpolation_string(
            to_std(resize_interpolation_->currentText())
        );
        transform.resize = resize;
    }

    switch (source_type_->currentIndex()) {
        case 0: {
            CameraSourceConfiguration source;
            source.device.backend = parse_camera_backend(
                to_std(camera_backend_->currentData().toString())
            ).value_or(CameraBackend::media_foundation);
            source.device.index = camera_index_->value();
            source.device.name = to_std(camera_name_->text());
            source.mode.width = camera_width_->value();
            source.mode.height = camera_height_->value();
            source.mode.fps = camera_fps_->value();
            source.mode.subtype_guid = to_std(camera_subtype_->text());
            source.request_60_fps = camera_request_60_->isChecked();
            source.transform = transform;
            result.source = source;
            break;
        }
        case 1:
            result.source = VideoSourceConfiguration{
                to_std(video_path_->text()),
                transform,
            };
            break;
        default:
            result.source = NdiSourceConfiguration{to_std(ndi_name_->text()), transform};
            break;
    }

    for (int row = 0; row < instance_table_->rowCount(); ++row) {
        const auto* port_item = instance_table_->item(row, 0);
        const auto* scenario_item = instance_table_->item(row, 1);
        InstanceConfiguration instance;
        bool ok = false;
        instance.connection.port = port_item ? port_item->text().toInt(&ok) : 0;
        if (!ok) {
            instance.connection.port = 0;
        }
        instance.scenario = scenario_item ? to_std(scenario_item->text()) : std::string{};
        result.instances.push_back(std::move(instance));
    }
    return result;
}

void ProfilePage::apply() {
    const auto profile = draft_profile();
    auto fail = [this](const QString& message) {
        status_label_->setText(message);
        QMessageBox::critical(this, tr("Profile"), message);
    };

    if (std::holds_alternative<CameraSourceConfiguration>(profile.source)) {
        const auto& camera = std::get<CameraSourceConfiguration>(profile.source);
        if (camera.device.name.empty()) {
            fail(tr("A camera device name is required. Use Detect cameras to select one."));
            return;
        }
        if (camera.mode.width <= 0 || camera.mode.height <= 0 || camera.mode.fps <= 0.0) {
            fail(tr("A camera capture mode is required. Use Detect cameras to select one."));
            return;
        }
        if (camera.mode.subtype_guid.empty()) {
            fail(tr("A camera subtype GUID is required. Use Detect cameras to select a mode."));
            return;
        }
    }
    if (std::holds_alternative<NdiSourceConfiguration>(profile.source)) {
        fail(tr("NDI input is not available in this build. Use camera or video input."));
        return;
    }
    if (std::holds_alternative<VideoSourceConfiguration>(profile.source)) {
        const auto& video = std::get<VideoSourceConfiguration>(profile.source);
        if (video.path.empty()) {
            fail(tr("A video file path is required."));
            return;
        }
        if (!std::filesystem::path{video.path}.is_absolute()) {
            fail(tr("The video file path must be absolute."));
            return;
        }
    }

    if (profile.instances.empty()) {
        fail(tr("Add at least one LiveSplit instance."));
        return;
    }
    for (const auto& instance : profile.instances) {
        if (instance.connection.port < 1 || instance.connection.port > 65535) {
            fail(tr("Bridge ports must be between 1 and 65535."));
            return;
        }
        const std::filesystem::path scenario{instance.scenario};
        if (instance.scenario.empty() || !scenario.is_absolute()) {
            fail(tr("Every scenario path must be absolute."));
            return;
        }
        if (scenario.extension() == ".py") {
            fail(tr("Python scenario modules are not supported: %1")
                .arg(QString::fromStdString(scenario.string())));
            return;
        }
        try {
            (void)load_profile_scenario(scenario, profile.source);
        } catch (const std::exception& error) {
            fail(tr("Scenario validation failed: %1").arg(QString::fromUtf8(error.what())));
            return;
        }
    }

    QString error;
    if (!controller_->apply_profile(profile, &error)) {
        fail(tr("Could not apply profile: %1").arg(error));
        return;
    }
    status_label_->setText(tr("Profile applied."));
    emit profileApplied();
    emit statusMessage(tr("Profile applied."));
}

void ProfilePage::add_instance() {
    const int row = instance_table_->rowCount();
    instance_table_->insertRow(row);
    instance_table_->setItem(row, 0, new QTableWidgetItem(QString::number(54000 + row)));
    instance_table_->setItem(row, 1, new QTableWidgetItem(QString{}));
}

void ProfilePage::remove_instance() {
    const int row = instance_table_->currentRow();
    if (row >= 0) {
        instance_table_->removeRow(row);
    }
}

void ProfilePage::browse_scenario() {
    const int row = instance_table_->currentRow();
    if (row < 0) {
        return;
    }
    const QString path = QFileDialog::getOpenFileName(
        this,
        tr("Select scenario"),
        {},
        tr("Scenario YAML (*.yaml *.yml)")
    );
    if (path.isEmpty()) {
        return;
    }
    if (auto* item = instance_table_->item(row, 1); item != nullptr) {
        item->setText(path);
    }
}

void ProfilePage::browse_video() {
    const QString path = QFileDialog::getOpenFileName(
        this,
        tr("Select video"),
        {},
        tr("Video files (*.mp4 *.mkv *.avi *.mov);;All files (*.*)")
    );
    if (!path.isEmpty()) {
        video_path_->setText(path);
    }
}

void ProfilePage::source_type_changed(int) {
    update_source_stack();
}

void ProfilePage::update_source_stack() {
    source_stack_->setCurrentIndex(source_type_->currentIndex());
}

void ProfilePage::refresh_camera_devices() {
    std::optional<CameraDeviceConfiguration> configured;
    if (!camera_name_->text().isEmpty()) {
        CameraDeviceConfiguration device;
        device.backend = parse_camera_backend(
            to_std(camera_backend_->currentData().toString())
        ).value_or(CameraBackend::media_foundation);
        device.name = to_std(camera_name_->text());
        device.index = camera_index_->value();
        configured = device;
    }
    std::optional<CameraModeConfiguration> mode;
    if (camera_width_->value() > 0 && camera_height_->value() > 0 && camera_fps_->value() > 0) {
        mode = CameraModeConfiguration{
            camera_width_->value(),
            camera_height_->value(),
            camera_fps_->value(),
            to_std(camera_subtype_->text()),
        };
    }
    populate_camera_devices(configured, mode);
}

void ProfilePage::populate_camera_devices(
    const std::optional<CameraDeviceConfiguration>& device,
    const std::optional<CameraModeConfiguration>& mode
) {
    try {
        camera_devices_ = list_camera_devices();
    } catch (const std::exception& error) {
        camera_devices_.clear();
        camera_note_->setText(
            tr("Could not enumerate cameras: %1").arg(QString::fromUtf8(error.what()))
        );
    }
    QSignalBlocker devices_block{camera_device_combo_};
    QSignalBlocker modes_block{camera_mode_combo_};
    camera_device_combo_->clear();
    camera_mode_combo_->clear();
    if (camera_devices_.empty()) {
        camera_note_->setText(tr("No camera devices were found."));
        return;
    }
    for (std::size_t index = 0; index < camera_devices_.size(); ++index) {
        const auto& entry = camera_devices_[index];
        camera_device_combo_->addItem(
            QStringLiteral("%1 [%2]")
                .arg(QString::fromStdString(entry.name))
                .arg(QString::fromStdString(std::string{to_string(entry.backend)})),
            static_cast<int>(index)
        );
    }

    int selected = -1;
    if (device.has_value()) {
        const auto resolved = resolve_camera_device(*device, camera_devices_);
        if (resolved.has_value()) {
            for (std::size_t index = 0; index < camera_devices_.size(); ++index) {
                if (camera_devices_[index].backend == resolved->backend &&
                    camera_devices_[index].index == resolved->index) {
                    selected = static_cast<int>(index);
                    break;
                }
            }
        } else {
            camera_note_->setText(tr("The configured camera is not connected."));
        }
    }
    camera_device_combo_->setCurrentIndex(selected);
    if (selected < 0) {
        return;
    }
    populate_camera_modes(camera_devices_[static_cast<std::size_t>(selected)].modes, mode);
}

void ProfilePage::populate_camera_modes(
    const std::vector<CameraModeInfo>& modes,
    const std::optional<CameraModeConfiguration>& configured
) {
    QSignalBlocker block{camera_mode_combo_};
    camera_modes_ = modes;
    camera_mode_combo_->clear();
    for (std::size_t index = 0; index < modes.size(); ++index) {
        const auto& mode = modes[index];
        camera_mode_combo_->addItem(
            QStringLiteral("%1x%2 @ %3 %4 (%5)")
                .arg(mode.width)
                .arg(mode.height)
                .arg(mode.fps, 0, 'f', 3)
                .arg(QString::fromStdString(mode.format))
                .arg(mode.subtype_selectable ? tr("exact subtype") : tr("size/FPS")),
            static_cast<int>(index)
        );
    }
    int selected = -1;
    if (configured.has_value()) {
        const auto resolved = try_resolve_camera_mode(*configured, modes);
        if (resolved.has_value()) {
            for (std::size_t index = 0; index < modes.size(); ++index) {
                if (modes[index] == *resolved) {
                    selected = static_cast<int>(index);
                    break;
                }
            }
        } else {
            camera_note_->setText(tr("The configured capture mode is unavailable."));
        }
    }
    camera_mode_combo_->setCurrentIndex(selected);
    if (selected >= 0) {
        const auto& mode = modes[static_cast<std::size_t>(selected)];
        camera_note_->setText(
            mode.subtype_selectable
                ? tr("The capture backend can select and verify this exact subtype.")
                : tr("This mode verifies width/height/FPS only; OpenCV does not expose "
                     "exact subtype selection for this backend.")
        );
    }
}

void ProfilePage::camera_device_changed(int index) {
    if (index < 0 || index >= static_cast<int>(camera_devices_.size())) {
        return;
    }
    const auto& device = camera_devices_[static_cast<std::size_t>(index)];
    camera_name_->setText(QString::fromStdString(device.name));
    camera_index_->setValue(device.index);
    const int backend_index = camera_backend_->findData(
        QString::fromStdString(std::string{to_string(device.backend)})
    );
    camera_backend_->setCurrentIndex(std::max(0, backend_index));
    CameraModeConfiguration configured{
        camera_width_->value(),
        camera_height_->value(),
        camera_fps_->value(),
        to_std(camera_subtype_->text()),
    };
    populate_camera_modes(device.modes, configured);
    if (camera_mode_combo_->currentIndex() < 0 && !device.modes.empty()) {
        camera_mode_combo_->setCurrentIndex(0);
        camera_mode_changed(0);
    }
    camera_note_->clear();
}

void ProfilePage::camera_mode_changed(int index) {
    if (index < 0 || index >= static_cast<int>(camera_modes_.size())) {
        return;
    }
    const auto& mode = camera_modes_[static_cast<std::size_t>(index)];
    camera_width_->setValue(mode.width);
    camera_height_->setValue(mode.height);
    camera_fps_->setValue(mode.fps);
    camera_subtype_->setText(QString::fromStdString(mode.subtype_guid));
    camera_note_->setText(
        mode.subtype_selectable
            ? tr("The capture backend can select and verify this exact subtype.")
            : tr("This mode verifies width/height/FPS only; OpenCV does not expose "
                 "exact subtype selection for this backend.")
    );
}

}  // namespace divergencesplitter::ui
