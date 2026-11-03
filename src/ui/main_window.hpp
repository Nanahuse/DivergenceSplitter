#pragma once

#include <QMainWindow>

#include <filesystem>
#include <optional>

#include "divergencesplitter/configuration/configuration.hpp"
#include "navigation_bar.hpp"

class QLabel;
class QResizeEvent;
class QStackedWidget;
class QTimer;
class QWidget;

namespace divergencesplitter::ui {

class AboutPage;
class AppController;
class DiagnosticsPage;
class MonitorPage;
class NotificationToast;
class ProfileHeader;
class ProfilePage;
class SettingsPage;

class MainWindow final : public QMainWindow {
    Q_OBJECT

public:
    explicit MainWindow(AppController* controller, QWidget* parent = nullptr);
    ~MainWindow() override;

protected:
    void resizeEvent(QResizeEvent* event) override;

private:
    void show_page(AppPage page);
    void open_profile();
    void save_profile();
    void save_profile_as();
    void new_profile();
    bool save_profile_to(const std::filesystem::path& path);
    void apply_theme(const QString& theme);
    void refresh_monitor();
    void refresh_diagnostics();
    void update_profile_header();
    void notify(const QString& message, bool error = false);

    AppController* controller_;
    NavigationBar* navigation_;
    ProfileHeader* profile_header_;
    QStackedWidget* pages_;
    QWidget* central_;
    MonitorPage* monitor_;
    DiagnosticsPage* diagnostics_;
    ProfilePage* profile_;
    SettingsPage* settings_;
    AboutPage* about_;
    NotificationToast* toast_;
    QTimer* monitor_timer_;
    QTimer* diagnostics_timer_;
    QTimer* header_timer_;
    std::optional<std::filesystem::path> profile_path_;
    Profile baseline_profile_;
};

}  // namespace divergencesplitter::ui
