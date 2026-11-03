#include "notification_toast.hpp"

#include <QLabel>
#include <QTimer>
#include <QVBoxLayout>

#include "theme.hpp"

namespace divergencesplitter::ui {

NotificationToast::NotificationToast(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("toast"));
    setAttribute(Qt::WA_TransparentForMouseEvents);
    setMaximumWidth(560);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(14, 9, 14, 9);
    label_ = new QLabel(this);
    label_->setWordWrap(true);
    layout->addWidget(label_);

    timer_ = new QTimer(this);
    timer_->setSingleShot(true);
    timer_->setInterval(3000);
    connect(timer_, &QTimer::timeout, this, &QWidget::hide);
    hide();
}

void NotificationToast::show_message(const QString& message, bool error) {
    if (message.isEmpty()) {
        return;
    }
    label_->setText(message);
    setProperty("error", error);
    theme::repolish(this);
    adjustSize();
    resize(qMin(width(), 560), sizeHint().height());
    show();
    raise();
    timer_->start();
}

void NotificationToast::place(const QRect& area) {
    adjustSize();
    const int width = qMin(sizeHint().width(), qMin(560, area.width() - 32));
    resize(width, sizeHint().height());
    move(area.center().x() - width / 2, area.bottom() - height() - 20);
}

}  // namespace divergencesplitter::ui
