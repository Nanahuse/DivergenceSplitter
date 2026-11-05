#pragma once

#include <QColor>
#include <QString>
#include <QStringView>
#include <QWidget>

class QApplication;

namespace divergencesplitter::ui::theme {

enum class Mode {
    light,
    dark,
};

struct SemanticColors {
    QColor active;
    QColor ready;
    QColor connecting;
    QColor failed;
    QColor stopped;
    QColor error;
    QColor warning;
    QColor primary;
    QColor on_primary;
    QColor muted;
    QColor background;
    QColor background_deep;
    QColor surface;
    QColor surface_low;
    QColor surface_high;
    QColor divider;
    QColor outline;
    QColor text;
    QColor text_secondary;
};

[[nodiscard]] Mode mode_from_string(QStringView value);
[[nodiscard]] Mode current_mode();
[[nodiscard]] QString mode_name(Mode mode);
[[nodiscard]] SemanticColors colors(Mode mode);
[[nodiscard]] QString stylesheet(Mode mode);
void apply(QApplication& application, Mode mode);
void repolish(QWidget* widget);

}  // namespace divergencesplitter::ui::theme
