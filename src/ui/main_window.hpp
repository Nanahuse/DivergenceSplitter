#pragma once

#include <QMainWindow>
#include <QString>

#include <filesystem>
#include <functional>
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
    struct FileDialogHooks {
        std::function<QString(const QString& title, const QString& initial, const QString& filter)>
            open_file;
        std::function<QString(const QString& title, const QString& initial, const QString& filter)>
            save_file;
        std::function<bool(const QString& title, const QString& message)> confirm_discard;
        std::function<void(const QString& title, const QString& message)> show_error;
    };

    explicit MainWindow(
        AppController* controller,
        QWidget* parent = nullptr,
        FileDialogHooks dialogs = {}
    );
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
    [[nodiscard]] bool has_unsaved_changes() const;
    [[nodiscard]] bool confirm_discard(const QString& title);

    AppController* controller_;
    FileDialogHooks dialogs_;
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
    std::optional<Profile> saved_profile_;
};

}  // namespace divergencesplitter::ui
