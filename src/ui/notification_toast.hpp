#pragma once

#include <QFrame>
#include <QRect>

class QLabel;
class QTimer;

namespace divergencesplitter::ui {

class NotificationToast final : public QFrame {
    Q_OBJECT

public:
    explicit NotificationToast(QWidget* parent = nullptr);

    void show_message(const QString& message, bool error = false);
    void place(const QRect& area);

private:
    QLabel* label_;
    QTimer* timer_;
};

}  // namespace divergencesplitter::ui
