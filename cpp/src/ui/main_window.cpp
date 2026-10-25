#include "divergencesplitter/ui/main_window.hpp"

#include <QAction>
#include <QApplication>
#include <QFileDialog>
#include <QMenuBar>
#include <QMessageBox>
#include <QPalette>
#include <QStatusBar>
#include <QStyle>
#include <QStyleFactory>
#include <QTabWidget>
#include <QTimer>

#include <filesystem>

#include "divergencesplitter/ui/about_page.hpp"
#include "divergencesplitter/ui/app_controller.hpp"
#include "divergencesplitter/ui/diagnostics_page.hpp"
#include "divergencesplitter/ui/monitor_page.hpp"
#include "divergencesplitter/ui/profile_page.hpp"
#include "divergencesplitter/ui/settings_page.hpp"

namespace divergencesplitter::ui {

MainWindow::MainWindow(AppController* controller, QWidget* parent)
    : QMainWindow(parent), controller_(controller) {
    setWindowTitle(tr("DivergenceSplitter"));
    resize(1100, 780);

    tabs_ = new QTabWidget(this);
    monitor_ = new MonitorPage(controller_, tabs_);
    diagnostics_ = new DiagnosticsPage(controller_, tabs_);
    profile_ = new ProfilePage(controller_, tabs_);
    settings_ = new SettingsPage(controller_, tabs_);
    about_ = new AboutPage(tabs_);
    tabs_->addTab(monitor_, tr("Monitor"));
    tabs_->addTab(diagnostics_, tr("Diagnostics"));
    tabs_->addTab(profile_, tr("Profile"));
    tabs_->addTab(settings_, tr("Settings"));
    tabs_->addTab(about_, tr("About"));
    setCentralWidget(tabs_);

    auto* file_menu = menuBar()->addMenu(tr("File"));
    auto* open_action = file_menu->addAction(tr("Open Profile..."));
    auto* save_action = file_menu->addAction(tr("Save Profile As..."));
    file_menu->addSeparator();
    auto* quit_action = file_menu->addAction(tr("Quit"));
    connect(open_action, &QAction::triggered, this, &MainWindow::open_profile);
    connect(save_action, &QAction::triggered, this, &MainWindow::save_profile_as);
    connect(quit_action, &QAction::triggered, qApp, &QApplication::quit);

    connect(monitor_, &MonitorPage::resetRequested, this, [this]() {
        controller_->request_reset_all();
        statusBar()->showMessage(tr("Manual reset requested for all scenarios."), 3000);
    });
    connect(profile_, &ProfilePage::profileApplied, this, [this]() {
        diagnostics_->refresh();
        monitor_->refresh();
        statusBar()->showMessage(tr("Profile applied."), 3000);
    });
    connect(profile_, &ProfilePage::statusMessage, this, [this](const QString& message) {
        statusBar()->showMessage(message, 3000);
    });
    connect(settings_, &SettingsPage::settingsSaved, this, [this](const QString& theme) {
        apply_theme(theme);
    });

    monitor_timer_ = new QTimer(this);
    monitor_timer_->setInterval(100);
    connect(monitor_timer_, &QTimer::timeout, this, &MainWindow::refresh_monitor);
    monitor_timer_->start();

    diagnostics_timer_ = new QTimer(this);
    diagnostics_timer_->setInterval(300);
    connect(diagnostics_timer_, &QTimer::timeout, this, &MainWindow::refresh_diagnostics);
    diagnostics_timer_->start();

    apply_theme(QString::fromStdString(controller_->settings().theme));
    refresh_monitor();
    refresh_diagnostics();
}

MainWindow::~MainWindow() {
    controller_->stop();
}

void MainWindow::refresh_monitor() {
    monitor_->refresh();
}

void MainWindow::refresh_diagnostics() {
    if (tabs_->currentWidget() == diagnostics_) {
        diagnostics_->refresh();
    }
}

void MainWindow::open_profile() {
    const QString path = QFileDialog::getOpenFileName(
        this,
        tr("Open Profile"),
        {},
        tr("Profile JSON (*.json);;All files (*.*)")
    );
    if (path.isEmpty()) {
        return;
    }
    QString error;
    if (!controller_->open_profile(std::filesystem::path{path.toStdWString()}, &error)) {
        QMessageBox::critical(this, tr("Open Profile"), error);
        return;
    }
    profile_->reload_from_controller();
    settings_->reload_from_controller();
    apply_theme(QString::fromStdString(controller_->settings().theme));
    statusBar()->showMessage(tr("Profile opened."), 3000);
    refresh_monitor();
    diagnostics_->refresh();
}

void MainWindow::save_profile_as() {
    const QString path = QFileDialog::getSaveFileName(
        this,
        tr("Save Profile As"),
        {},
        tr("Profile JSON (*.json)")
    );
    if (path.isEmpty()) {
        return;
    }
    QString error;
    if (!controller_->save_profile_file(
            std::filesystem::path{path.toStdWString()},
            profile_->draft_profile(),
            &error
        )) {
        QMessageBox::critical(this, tr("Save Profile"), error);
        return;
    }
    statusBar()->showMessage(tr("Profile saved."), 3000);
}

void MainWindow::apply_theme(const QString& theme) {
    QApplication::setStyle(QStyleFactory::create(QStringLiteral("Fusion")));
    QPalette palette;
    if (theme == QStringLiteral("dark")) {
        palette.setColor(QPalette::Window, QColor(45, 45, 48));
        palette.setColor(QPalette::WindowText, QColor(230, 230, 230));
        palette.setColor(QPalette::Base, QColor(30, 30, 30));
        palette.setColor(QPalette::AlternateBase, QColor(45, 45, 48));
        palette.setColor(QPalette::Text, QColor(230, 230, 230));
        palette.setColor(QPalette::Button, QColor(60, 60, 64));
        palette.setColor(QPalette::ButtonText, QColor(230, 230, 230));
        palette.setColor(QPalette::Highlight, QColor(42, 130, 218));
        palette.setColor(QPalette::HighlightedText, Qt::white);
        palette.setColor(QPalette::ToolTipBase, QColor(45, 45, 48));
        palette.setColor(QPalette::ToolTipText, QColor(230, 230, 230));
        palette.setColor(QPalette::Disabled, QPalette::Text, QColor(120, 120, 120));
    } else {
        palette = QApplication::style()->standardPalette();
    }
    QApplication::setPalette(palette);
}

}  // namespace divergencesplitter::ui
