#include "divergencesplitter/ui/reset_all_button.hpp"

#include <QMouseEvent>

namespace divergencesplitter::ui {

ResetAllButton::ResetAllButton(QWidget* parent) : QPushButton(parent) {
    setMinimumHeight(38);
    timer_.setInterval(50);
    connect(&timer_, &QTimer::timeout, this, [this]() {
        if (!holding_) {
            return;
        }
        if (elapsed_.elapsed() >= hold_duration_ms_) {
            holding_ = false;
            timer_.stop();
            update_text();
            emit holdCompleted();
            return;
        }
        update_text();
    });
    update_text();
}

void ResetAllButton::set_hold_duration_ms(int duration_ms) {
    hold_duration_ms_ = std::max(1, duration_ms);
    update_text();
}

void ResetAllButton::mousePressEvent(QMouseEvent* event) {
    if (event->button() != Qt::LeftButton) {
        QPushButton::mousePressEvent(event);
        return;
    }
    holding_ = true;
    elapsed_.restart();
    timer_.start();
    update_text();
    event->accept();
}

void ResetAllButton::mouseReleaseEvent(QMouseEvent* event) {
    if (holding_) {
        cancel_hold();
        event->accept();
        return;
    }
    QPushButton::mouseReleaseEvent(event);
}

void ResetAllButton::leaveEvent(QEvent* event) {
    cancel_hold();
    QPushButton::leaveEvent(event);
}

void ResetAllButton::cancel_hold() {
    if (!holding_) {
        return;
    }
    holding_ = false;
    timer_.stop();
    update_text();
}

void ResetAllButton::update_text() {
    if (!holding_) {
        setText(tr("Hold %1 ms to Reset All").arg(hold_duration_ms_));
        return;
    }
    const int remaining = std::max(0, hold_duration_ms_ - static_cast<int>(elapsed_.elapsed()));
    setText(tr("Keep holding... %1 ms").arg(remaining));
}

}  // namespace divergencesplitter::ui
