#pragma once

#include <QMainWindow>

class QTabWidget;
class QTimer;

namespace divergencesplitter::ui {

class AboutPage;
class AppController;
class DiagnosticsPage;
class MonitorPage;
class ProfilePage;
class SettingsPage;

class MainWindow final : public QMainWindow {
    Q_OBJECT

public:
    explicit MainWindow(AppController* controller, QWidget* parent = nullptr);
    ~MainWindow() override;

private:
    void open_profile();
    void save_profile_as();
    void apply_theme(const QString& theme);
    void refresh_monitor();
    void refresh_diagnostics();

    AppController* controller_;
    QTabWidget* tabs_;
    MonitorPage* monitor_;
    DiagnosticsPage* diagnostics_;
    ProfilePage* profile_;
    SettingsPage* settings_;
    AboutPage* about_;
    QTimer* monitor_timer_;
    QTimer* diagnostics_timer_;
};

}  // namespace divergencesplitter::ui
