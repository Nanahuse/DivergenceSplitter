#include "theme.hpp"

#include <QApplication>
#include <QPalette>
#include <QStyle>
#include <QStyleFactory>

namespace divergencesplitter::ui::theme {
namespace {

struct Palette {
    const char* background;
    const char* background_deep;
    const char* surface;
    const char* surface_low;
    const char* surface_high;
    const char* divider;
    const char* outline;
    const char* text;
    const char* text_secondary;
    const char* primary;
    const char* on_primary;
    const char* ready;
    const char* active;
    const char* connecting;
    const char* failed;
    const char* stopped;
    const char* warning;
    const char* error;
    const char* muted;
};

constexpr Palette light_palette{
    "#F7F5F1",
    "#EFEBE4",
    "#FFFFFF",
    "#F4F1EB",
    "#EAE5DC",
    "#DDD7CC",
    "#B8B0A2",
    "#1D1C19",
    "#676158",
    "#F08A35",
    "#FFFFFF",
    "#4CAF50",
    "#FFB300",
    "#FFB300",
    "#E53935",
    "#9E9E9E",
    "#FFB300",
    "#E53935",
    "#9E9E9E",
};

constexpr Palette dark_palette{
    "#111512",
    "#0B0E0C",
    "#1A201B",
    "#151A16",
    "#212921",
    "#354039",
    "#5E6A60",
    "#E7E1D3",
    "#B4B2A8",
    "#F08A35",
    "#251207",
    "#78C99A",
    "#78C99A",
    "#D4AD54",
    "#E06B64",
    "#7D8981",
    "#D4AD54",
    "#E06B64",
    "#7D8981",
};

[[nodiscard]] const Palette& palette_for(Mode mode) {
    return mode == Mode::dark ? dark_palette : light_palette;
}

}  // namespace

Mode mode_from_string(QStringView value) {
    return value.compare(QStringLiteral("dark"), Qt::CaseInsensitive) == 0
        ? Mode::dark
        : Mode::light;
}

Mode current_mode() {
    return QApplication::palette().color(QPalette::Window).lightness() < 128
        ? Mode::dark
        : Mode::light;
}

QString mode_name(Mode mode) {
    return mode == Mode::dark ? QStringLiteral("dark") : QStringLiteral("light");
}

SemanticColors colors(Mode mode) {
    const auto& palette = palette_for(mode);
    return SemanticColors{
        QColor(QString::fromLatin1(palette.active)),
        QColor(QString::fromLatin1(palette.ready)),
        QColor(QString::fromLatin1(palette.connecting)),
        QColor(QString::fromLatin1(palette.failed)),
        QColor(QString::fromLatin1(palette.stopped)),
        QColor(QString::fromLatin1(palette.error)),
        QColor(QString::fromLatin1(palette.warning)),
        QColor(QString::fromLatin1(palette.primary)),
        QColor(QString::fromLatin1(palette.on_primary)),
        QColor(QString::fromLatin1(palette.muted)),
        QColor(QString::fromLatin1(palette.background)),
        QColor(QString::fromLatin1(palette.background_deep)),
        QColor(QString::fromLatin1(palette.surface)),
        QColor(QString::fromLatin1(palette.surface_low)),
        QColor(QString::fromLatin1(palette.surface_high)),
        QColor(QString::fromLatin1(palette.divider)),
        QColor(QString::fromLatin1(palette.outline)),
        QColor(QString::fromLatin1(palette.text)),
        QColor(QString::fromLatin1(palette.text_secondary)),
    };
}

QString stylesheet(Mode mode) {
    const auto& palette = palette_for(mode);
    const auto color = [](const char* value) { return QString::fromLatin1(value); };
    QString result = QStringLiteral(R"(
QWidget {
    color: %1;
    selection-background-color: %2;
    selection-color: %3;
}
QMainWindow, QWidget#appRoot, QWidget#page, QWidget#navPanel, QWidget#contentPanel,
QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget, QDialog {
    background-color: %4;
}
QFrame#card, QFrame#profileHeader, QGroupBox {
    background-color: %5;
    border: 1px solid %6;
    border-radius: 10px;
}
QFrame#profileHeader {
    border-radius: 0px;
    border-left: 0px;
    border-right: 0px;
    border-top: 0px;
}
QGroupBox {
    margin-top: 18px;
    padding: 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0px 4px;
    color: %7;
}
QLabel#pageTitle {
    font-size: 22px;
    font-weight: 600;
}
QLabel#sectionTitle {
    font-size: 15px;
    font-weight: 600;
}
QLabel#cardTitle {
    font-size: 15px;
    font-weight: 600;
}
QLabel#muted, QLabel#hint {
    color: %7;
}
QLabel#dirtyMarker {
    color: %8;
    font-weight: 600;
}
QLabel#errorBanner {
    background-color: %5;
    border: 1px solid %9;
    border-radius: 8px;
    color: %9;
    padding: 8px;
}
QPushButton {
    background-color: %10;
    border: 1px solid %11;
    border-radius: 7px;
    padding: 6px 12px;
    min-height: 20px;
}
QPushButton:hover {
    border-color: %2;
}
QPushButton:pressed {
    background-color: %6;
}
QPushButton:default, QPushButton#primaryButton {
    background-color: %2;
    border-color: %2;
    color: %3;
    font-weight: 600;
}
QPushButton:default:hover, QPushButton#primaryButton:hover {
    background-color: %12;
    border-color: %12;
}
QPushButton:disabled {
    color: %13;
    background-color: %5;
    border-color: %6;
}
QToolButton#navButton {
    border: 0px;
    border-radius: 8px;
    padding: 8px;
    color: %7;
    background-color: transparent;
    text-align: left;
}
QToolButton#navButton:hover {
    background-color: %6;
}
QToolButton#navButton:checked {
    background-color: %5;
    color: %2;
    font-weight: 600;
}
QToolButton#navToggle {
    border: 0px;
    border-radius: 8px;
    color: %7;
    background-color: transparent;
}
QToolButton#navToggle:hover {
    background-color: %6;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser, QTextEdit {
    background-color: %14;
    border: 1px solid %11;
    border-radius: 7px;
    padding: 5px 7px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: %2;
}
QLineEdit:read-only {
    color: %7;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    border: 0px;
    width: 18px;
}
QAbstractItemView {
    background-color: %5;
    border: 1px solid %6;
    border-radius: 7px;
    selection-background-color: %2;
    selection-color: %3;
    alternate-background-color: %14;
}
QHeaderView::section {
    background-color: %14;
    color: %7;
    border: 0px;
    border-bottom: 1px solid %6;
    padding: 6px;
}
QTableWidget, QTreeWidget, QTableView, QTreeView {
    background-color: %5;
    border: 1px solid %6;
    border-radius: 7px;
    gridline-color: %6;
}
QTabWidget::pane {
    border: 1px solid %6;
    border-radius: 8px;
    background-color: %5;
    top: -1px;
}
QTabBar::tab {
    background-color: transparent;
    color: %7;
    padding: 8px 16px;
    margin-right: 4px;
    border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
    color: %2;
    border-bottom: 2px solid %2;
    font-weight: 600;
}
QTabBar::tab:hover {
    color: %1;
}
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 0px;
}
QScrollBar::handle:vertical {
    background: %11;
    min-height: 28px;
    border-radius: 5px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
}
QScrollBar::handle:horizontal {
    background: %11;
    min-width: 28px;
    border-radius: 5px;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}
QSplitter::handle, QMainWindow::separator {
    background-color: %6;
}
QStatusBar {
    background-color: %4;
    color: %7;
}
QStatusBar::item {
    border: 0px;
}
QToolTip {
    background-color: %5;
    color: %1;
    border: 1px solid %11;
    padding: 4px;
}
QFrame#toast {
    background-color: %5;
    border: 1px solid %6;
    border-radius: 9px;
}
QFrame#toast[error="true"] {
    border-color: %9;
}
QFrame#scenarioCard {
    background-color: %5;
    border: 1px solid %6;
    border-radius: 10px;
}
QFrame#scenarioCard:hover {
    border-color: %11;
}
QFrame#dividerHorizontal {
    background-color: %6;
    border: 0px;
    max-height: 1px;
}
QFrame#dividerVertical {
    background-color: %6;
    border: 0px;
    max-width: 1px;
}
QLabel#stateReady { color: %15; font-weight: 600; }
QLabel#stateConnecting { color: %16; font-weight: 600; }
QLabel#stateFailed { color: %9; font-weight: 600; }
QLabel#stateStopped { color: %13; font-weight: 600; }
QLabel[role="error"] { color: %9; }
QLabel[role="muted"] { color: %7; }
QLabel[role="ready"] { color: %15; font-weight: 600; }
QLabel[role="warning"] { color: %8; font-weight: 600; }
QLabel[role="failed"] { color: %9; font-weight: 600; }
QLabel[role="stopped"] { color: %13; }
)");

    const auto replace = [&result, &color](const char* token, const char* value) {
        result.replace(QLatin1String(token), color(value));
    };
    replace("%16", palette.connecting);
    replace("%15", palette.ready);
    replace("%14", palette.surface_low);
    replace("%13", palette.muted);
    replace("%12", palette.active);
    replace("%11", palette.outline);
    replace("%10", palette.surface_high);
    replace("%9", palette.error);
    replace("%8", palette.warning);
    replace("%7", palette.text_secondary);
    replace("%6", palette.divider);
    replace("%5", palette.surface);
    replace("%4", palette.background);
    replace("%3", palette.on_primary);
    replace("%2", palette.primary);
    replace("%1", palette.text);
    return result;
}

void apply(QApplication& application, Mode mode) {
    application.setStyle(QStyleFactory::create(QStringLiteral("Fusion")));
    QPalette palette;
    const auto tokens = colors(mode);
    palette.setColor(QPalette::Window, tokens.background);
    palette.setColor(QPalette::WindowText, tokens.text);
    palette.setColor(QPalette::Base, tokens.surface_low);
    palette.setColor(QPalette::AlternateBase, tokens.surface);
    palette.setColor(QPalette::Text, tokens.text);
    palette.setColor(QPalette::Button, tokens.surface_high);
    palette.setColor(QPalette::ButtonText, tokens.text);
    palette.setColor(QPalette::Highlight, tokens.primary);
    palette.setColor(QPalette::HighlightedText, tokens.on_primary);
    palette.setColor(QPalette::ToolTipBase, tokens.surface);
    palette.setColor(QPalette::ToolTipText, tokens.text);
    palette.setColor(QPalette::PlaceholderText, tokens.muted);
    palette.setColor(QPalette::Disabled, QPalette::Text, tokens.muted);
    palette.setColor(QPalette::Disabled, QPalette::ButtonText, tokens.muted);
    application.setPalette(palette);
    application.setStyleSheet(stylesheet(mode));
}

void repolish(QWidget* widget) {
    if (widget == nullptr) {
        return;
    }
    widget->style()->unpolish(widget);
    widget->style()->polish(widget);
    widget->update();
}

}  // namespace divergencesplitter::ui::theme
