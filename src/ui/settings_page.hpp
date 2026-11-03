#pragma once

#include <QString>
#include <QWidget>

class QComboBox;
class QLabel;
class QSpinBox;

namespace divergencesplitter::ui {

class AppController;

class SettingsPage final : public QWidget {
    Q_OBJECT

public:
    explicit SettingsPage(AppController* controller, QWidget* parent = nullptr);

    void reload_from_controller();

signals:
    void settingsSaved(const QString& theme);

private:
    void save();

    AppController* controller_;
    QComboBox* log_level_;
    QSpinBox* reaction_time_;
    QComboBox* theme_;
    QLabel* status_;
};

}  // namespace divergencesplitter::ui
