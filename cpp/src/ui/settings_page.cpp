#include "divergencesplitter/ui/settings_page.hpp"

#include <QComboBox>
#include <QFormLayout>
#include <QHBoxLayout>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QSpinBox>
#include <QVBoxLayout>

#include "divergencesplitter/ui/app_controller.hpp"

namespace divergencesplitter::ui {

SettingsPage::SettingsPage(AppController* controller, QWidget* parent)
    : QWidget(parent), controller_(controller) {
    auto* layout = new QVBoxLayout(this);
    auto* title = new QLabel(tr("Settings"), this);
    QFont title_font = title->font();
    title_font.setPointSize(title_font.pointSize() + 4);
    title_font.setBold(true);
    title->setFont(title_font);
    layout->addWidget(title);

    auto* form = new QFormLayout;
    log_level_ = new QComboBox(this);
    log_level_->addItems({"OFF", "DEBUG", "INFO", "WARNING", "ERROR"});
    reaction_time_ = new QSpinBox(this);
    reaction_time_->setRange(0, 5000);
    reaction_time_->setSuffix(tr(" ms"));
    theme_ = new QComboBox(this);
    theme_->addItems({tr("Light"), tr("Dark")});
    form->addRow(tr("Log level"), log_level_);
    form->addRow(tr("Reaction time"), reaction_time_);
    form->addRow(tr("Theme"), theme_);
    layout->addLayout(form);

    status_ = new QLabel(this);
    layout->addWidget(status_);
    layout->addStretch(1);

    auto* buttons = new QHBoxLayout;
    auto* reload = new QPushButton(tr("Reload"), this);
    auto* save = new QPushButton(tr("Save"), this);
    buttons->addWidget(reload);
    buttons->addStretch(1);
    buttons->addWidget(save);
    layout->addLayout(buttons);

    connect(reload, &QPushButton::clicked, this, &SettingsPage::reload_from_controller);
    connect(save, &QPushButton::clicked, this, &SettingsPage::save);

    reload_from_controller();
}

void SettingsPage::reload_from_controller() {
    const auto& settings = controller_->settings();
    const int log_index = log_level_->findText(QString::fromStdString(settings.log_level));
    log_level_->setCurrentIndex(std::max(0, log_index));
    reaction_time_->setValue(settings.reaction_time_ms);
    theme_->setCurrentIndex(settings.theme == "dark" ? 1 : 0);
    status_->setText(tr("Settings loaded. Reaction time applies on the next Apply."));
}

void SettingsPage::save() {
    auto settings = controller_->settings();
    settings.log_level = log_level_->currentText().toStdString();
    settings.reaction_time_ms = reaction_time_->value();
    settings.theme = theme_->currentIndex() == 1 ? "dark" : "light";
    QString error;
    controller_->save_settings(settings, &error);
    if (!error.isEmpty()) {
        status_->setText(error);
        QMessageBox::critical(this, tr("Settings"), error);
        return;
    }
    status_->setText(tr("Settings saved."));
    emit settingsSaved(QString::fromStdString(settings.theme));
}

}  // namespace divergencesplitter::ui
