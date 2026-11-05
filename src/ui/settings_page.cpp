#include "settings_page.hpp"

#include <QComboBox>
#include <QFormLayout>
#include <QFrame>
#include <QGroupBox>
#include <QHBoxLayout>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QScrollArea>
#include <QSpinBox>
#include <QVBoxLayout>

#include "app_controller.hpp"

namespace divergencesplitter::ui {

SettingsPage::SettingsPage(AppController* controller, QWidget* parent)
    : QWidget(parent), controller_(controller) {
    setObjectName(QStringLiteral("page"));
    auto* outer = new QVBoxLayout(this);
    outer->setContentsMargins(24, 20, 24, 20);
    outer->setSpacing(10);

    auto* title = new QLabel(tr("Application Settings"), this);
    title->setObjectName(QStringLiteral("pageTitle"));
    outer->addWidget(title);
    auto* note = new QLabel(
        tr("Edit the values, then select Apply to save and apply them."), this
    );
    note->setProperty("role", QStringLiteral("muted"));
    outer->addWidget(note);

    auto* scroll = new QScrollArea(this);
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    auto* content = new QWidget(scroll);
    content->setObjectName(QStringLiteral("page"));
    auto* layout = new QVBoxLayout(content);
    layout->setContentsMargins(0, 8, 0, 8);
    layout->setSpacing(12);

    auto* appearance = new QGroupBox(tr("Appearance"), content);
    auto* appearance_layout = new QFormLayout(appearance);
    theme_ = new QComboBox(appearance);
    theme_->setObjectName(QStringLiteral("settingsTheme"));
    theme_->setFixedWidth(220);
    theme_->addItems({tr("Light"), tr("Dark")});
    appearance_layout->addRow(tr("Theme"), theme_);
    layout->addWidget(appearance);

    auto* runtime = new QGroupBox(tr("Runtime"), content);
    auto* runtime_layout = new QFormLayout(runtime);
    reaction_time_ = new QSpinBox(runtime);
    reaction_time_->setObjectName(QStringLiteral("settingsReactionTime"));
    reaction_time_->setFixedWidth(220);
    reaction_time_->setRange(0, 5000);
    reaction_time_->setSuffix(tr(" ms"));
    runtime_layout->addRow(tr("Reaction time"), reaction_time_);
    layout->addWidget(runtime);

    auto* logging = new QGroupBox(tr("Logging"), content);
    auto* logging_layout = new QFormLayout(logging);
    log_level_ = new QComboBox(logging);
    log_level_->setObjectName(QStringLiteral("settingsLogLevel"));
    log_level_->setFixedWidth(220);
    log_level_->addItems({"OFF", "DEBUG", "INFO", "WARNING", "ERROR"});
    logging_layout->addRow(tr("Log level"), log_level_);
    auto* log_note = new QLabel(tr("DEBUG log: see diagnostics.log"), logging);
    log_note->setProperty("role", QStringLiteral("muted"));
    logging_layout->addRow(log_note);
    layout->addWidget(logging);
    layout->addStretch(1);

    scroll->setWidget(content);
    outer->addWidget(scroll, 1);

    status_ = new QLabel(this);
    status_->setProperty("role", QStringLiteral("muted"));
    status_->setWordWrap(true);
    outer->addWidget(status_);

    auto* buttons = new QHBoxLayout;
    auto* reload = new QPushButton(tr("Reload"), this);
    auto* save = new QPushButton(tr("Apply"), this);
    save->setObjectName(QStringLiteral("primaryButton"));
    buttons->addWidget(reload);
    buttons->addStretch(1);
    buttons->addWidget(save);
    outer->addLayout(buttons);

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
