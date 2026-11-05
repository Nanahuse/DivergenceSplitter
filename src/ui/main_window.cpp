#include "main_window.hpp"

#include <QAction>
#include <QApplication>
#include <QFileDialog>
#include <QFrame>
#include <QHBoxLayout>
#include <QMenuBar>
#include <QMessageBox>
#include <QResizeEvent>
#include <QStackedWidget>
#include <QTimer>
#include <QVBoxLayout>

#include <filesystem>
#include <utility>

#include "about_page.hpp"
#include "app_controller.hpp"
#include "diagnostics_page.hpp"
#include "monitor_page.hpp"
#include "notification_toast.hpp"
#include "profile_header.hpp"
#include "profile_page.hpp"
#include "settings_page.hpp"
#include "theme.hpp"

namespace divergencesplitter::ui {
namespace {

bool profiles_equal(const Profile& left, const Profile& right) {
    return left.version == right.version && left.source == right.source &&
           left.instances == right.instances;
}

QString display_path(const std::optional<std::filesystem::path>& path) {
    return path.has_value() ? QString::fromStdWString(path->wstring())
                            : QObject::tr("No profile selected");
}

}  // namespace

MainWindow::MainWindow(AppController* controller, QWidget* parent, FileDialogHooks dialogs)
    : QMainWindow(parent), controller_(controller), dialogs_(std::move(dialogs)) {
    if (!dialogs_.open_file) {
        dialogs_.open_file = [this](
                                 const QString& title,
                                 const QString& initial,
                                 const QString& filter
                             ) {
            return QFileDialog::getOpenFileName(this, title, initial, filter);
        };
    }
    if (!dialogs_.save_file) {
        dialogs_.save_file = [this](
                                 const QString& title,
                                 const QString& initial,
                                 const QString& filter
                             ) {
            return QFileDialog::getSaveFileName(this, title, initial, filter);
        };
    }
    if (!dialogs_.confirm_discard) {
        dialogs_.confirm_discard = [this](const QString& title, const QString& message) {
            return QMessageBox::question(this, title, message) == QMessageBox::Yes;
        };
    }
    if (!dialogs_.show_error) {
        dialogs_.show_error = [this](const QString& title, const QString& message) {
            QMessageBox::critical(this, title, message);
        };
    }

    setWindowTitle(tr("DivergenceSplitter"));
    resize(1200, 900);
    setMinimumSize(900, 600);

    central_ = new QWidget(this);
    central_->setObjectName(QStringLiteral("appRoot"));
    auto* root = new QHBoxLayout(central_);
    root->setContentsMargins(0, 0, 0, 0);
    root->setSpacing(0);

    navigation_ = new NavigationBar(central_);
    root->addWidget(navigation_);

    auto* divider = new QFrame(central_);
    divider->setObjectName(QStringLiteral("dividerVertical"));
    divider->setFrameShape(QFrame::VLine);
    divider->setFixedWidth(1);
    root->addWidget(divider);

    auto* content = new QWidget(central_);
    content->setObjectName(QStringLiteral("contentPanel"));
    auto* content_layout = new QVBoxLayout(content);
    content_layout->setContentsMargins(0, 0, 0, 0);
    content_layout->setSpacing(0);

    profile_header_ = new ProfileHeader(content);
    content_layout->addWidget(profile_header_);

    auto* header_divider = new QFrame(content);
    header_divider->setObjectName(QStringLiteral("dividerHorizontal"));
    header_divider->setFrameShape(QFrame::HLine);
    header_divider->setFixedHeight(1);
    content_layout->addWidget(header_divider);

    pages_ = new QStackedWidget(content);
    monitor_ = new MonitorPage(controller_, pages_);
    diagnostics_ = new DiagnosticsPage(controller_, pages_);
    profile_ = new ProfilePage(controller_, pages_);
    settings_ = new SettingsPage(controller_, pages_);
    about_ = new AboutPage(pages_);
    pages_->addWidget(monitor_);
    pages_->addWidget(diagnostics_);
    pages_->addWidget(profile_);
    pages_->addWidget(settings_);
    pages_->addWidget(about_);
    content_layout->addWidget(pages_, 1);
    root->addWidget(content, 1);
    setCentralWidget(central_);

    toast_ = new NotificationToast(central_);

    auto* file_menu = menuBar()->addMenu(tr("File"));
    auto* new_action = file_menu->addAction(tr("New Profile..."));
    auto* open_action = file_menu->addAction(tr("Open Profile..."));
    auto* save_action = file_menu->addAction(tr("Save Profile"));
    auto* save_as_action = file_menu->addAction(tr("Save Profile As..."));
    file_menu->addSeparator();
    auto* quit_action = file_menu->addAction(tr("Quit"));
    connect(new_action, &QAction::triggered, this, &MainWindow::new_profile);
    connect(open_action, &QAction::triggered, this, &MainWindow::open_profile);
    connect(save_action, &QAction::triggered, this, &MainWindow::save_profile);
    connect(save_as_action, &QAction::triggered, this, &MainWindow::save_profile_as);
    connect(quit_action, &QAction::triggered, qApp, &QApplication::quit);

    connect(navigation_, &NavigationBar::pageSelected, this, &MainWindow::show_page);
    connect(profile_header_, &ProfileHeader::newRequested, this, &MainWindow::new_profile);
    connect(profile_header_, &ProfileHeader::openRequested, this, &MainWindow::open_profile);
    connect(profile_header_, &ProfileHeader::saveRequested, this, &MainWindow::save_profile);
    connect(
        profile_header_, &ProfileHeader::saveAsRequested, this, &MainWindow::save_profile_as
    );

    connect(monitor_, &MonitorPage::resetRequested, this, [this]() {
        controller_->request_reset_all();
        notify(tr("Manual reset requested for all scenarios."));
    });
    connect(profile_, &ProfilePage::profileApplied, this, [this]() {
        refresh_diagnostics();
        refresh_monitor();
        update_profile_header();
        notify(tr("Profile applied."));
    });
    connect(settings_, &SettingsPage::settingsSaved, this, [this](const QString& theme) {
        apply_theme(theme);
        notify(tr("Settings saved."));
    });

    monitor_timer_ = new QTimer(this);
    monitor_timer_->setInterval(100);
    connect(monitor_timer_, &QTimer::timeout, this, &MainWindow::refresh_monitor);
    monitor_timer_->start();

    diagnostics_timer_ = new QTimer(this);
    diagnostics_timer_->setInterval(300);
    connect(diagnostics_timer_, &QTimer::timeout, this, &MainWindow::refresh_diagnostics);
    diagnostics_timer_->start();

    header_timer_ = new QTimer(this);
    header_timer_->setInterval(250);
    connect(header_timer_, &QTimer::timeout, this, &MainWindow::update_profile_header);
    header_timer_->start();

    profile_path_ = controller_->profile_path();
    saved_profile_ = profile_->draft_profile();
    apply_theme(QString::fromStdString(controller_->settings().theme));
    refresh_monitor();
    refresh_diagnostics();
    update_profile_header();
}

MainWindow::~MainWindow() {
    profile_->hide();
    controller_->stop();
}

void MainWindow::show_page(AppPage page) {
    QWidget* target = monitor_;
    switch (page) {
        case AppPage::monitor:
            target = monitor_;
            break;
        case AppPage::diagnostics:
            target = diagnostics_;
            break;
        case AppPage::profile:
            target = profile_;
            break;
        case AppPage::settings:
            target = settings_;
            break;
        case AppPage::about:
            target = about_;
            break;
    }
    pages_->setCurrentWidget(target);
    navigation_->set_current_page(page);
    if (page == AppPage::monitor) {
        refresh_monitor();
    } else if (page == AppPage::diagnostics) {
        refresh_diagnostics();
    }
}

void MainWindow::refresh_monitor() {
    if (pages_->currentWidget() == monitor_) {
        monitor_->refresh();
    }
}

void MainWindow::refresh_diagnostics() {
    if (pages_->currentWidget() == diagnostics_) {
        diagnostics_->refresh();
    }
}

bool MainWindow::has_unsaved_changes() const {
    return !saved_profile_.has_value() ||
           !profiles_equal(profile_->draft_profile(), *saved_profile_);
}

bool MainWindow::confirm_discard(const QString& title) {
    return !has_unsaved_changes() ||
           dialogs_.confirm_discard(title, tr("Discard the unsaved Profile changes?"));
}

void MainWindow::update_profile_header() {
    const bool dirty = has_unsaved_changes();
    profile_header_->sync(display_path(profile_path_), dirty, true, true);
}

void MainWindow::notify(const QString& message, bool error) {
    if (message.isEmpty()) {
        return;
    }
    toast_->show_message(message, error);
    toast_->place(central_->rect());
    toast_->raise();
}

void MainWindow::new_profile() {
    if (!confirm_discard(tr("New Profile"))) {
        return;
    }
    const QString path = dialogs_.save_file(
        tr("New Profile"),
        QStringLiteral("profile.json"),
        tr("Profile JSON (*.json)")
    );
    if (path.isEmpty()) {
        return;
    }
    Profile profile;
    profile_->load_draft(profile);
    profile_path_ = std::filesystem::path{path.toStdWString()};
    saved_profile_.reset();
    update_profile_header();
    notify(tr("New profile; save to apply it."));
}

void MainWindow::open_profile() {
    if (!confirm_discard(tr("Open Profile"))) {
        return;
    }
    const QString path = dialogs_.open_file(
        tr("Open Profile"),
        {},
        tr("Profile JSON (*.json);;All files (*.*)")
    );
    if (path.isEmpty()) {
        return;
    }
    QString error;
    if (!controller_->open_profile(std::filesystem::path{path.toStdWString()}, &error)) {
        notify(error, true);
        dialogs_.show_error(tr("Open Profile"), error);
        return;
    }
    profile_->reload_from_controller();
    settings_->reload_from_controller();
    apply_theme(QString::fromStdString(controller_->settings().theme));
    profile_path_ = controller_->profile_path();
    saved_profile_ = profile_->draft_profile();
    update_profile_header();
    refresh_monitor();
    refresh_diagnostics();
    notify(tr("Profile opened."));
}

bool MainWindow::save_profile_to(const std::filesystem::path& path) {
    QString error;
    if (!controller_->save_profile_file(path, profile_->draft_profile(), &error)) {
        notify(error, true);
        dialogs_.show_error(tr("Save Profile"), error);
        return false;
    }
    profile_path_ = controller_->profile_path();
    saved_profile_ = profile_->draft_profile();
    update_profile_header();
    notify(tr("Profile saved."));
    return true;
}

void MainWindow::save_profile() {
    if (!profile_path_.has_value()) {
        save_profile_as();
        return;
    }
    (void)save_profile_to(*profile_path_);
}

void MainWindow::save_profile_as() {
    const QString initial = profile_path_.has_value()
        ? QString::fromStdWString(profile_path_->wstring())
        : QStringLiteral("profile.json");
    const QString path = dialogs_.save_file(
        tr("Save Profile As"),
        initial,
        tr("Profile JSON (*.json)")
    );
    if (path.isEmpty()) {
        return;
    }
    (void)save_profile_to(std::filesystem::path{path.toStdWString()});
}

void MainWindow::apply_theme(const QString& theme) {
    theme::apply(*qApp, theme::mode_from_string(theme));
    monitor_->refresh();
    diagnostics_->refresh();
    profile_->refresh_preview();
    theme::repolish(profile_header_);
    theme::repolish(navigation_);
    theme::repolish(central_);
}

void MainWindow::resizeEvent(QResizeEvent* event) {
    QMainWindow::resizeEvent(event);
    if (toast_ != nullptr) {
        toast_->place(central_->rect());
    }
}

}  // namespace divergencesplitter::ui
