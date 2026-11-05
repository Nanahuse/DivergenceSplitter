#pragma once

#include <QWidget>

namespace divergencesplitter::ui {

class AboutPage final : public QWidget {
    Q_OBJECT

public:
    explicit AboutPage(QWidget* parent = nullptr);
};

}  // namespace divergencesplitter::ui
