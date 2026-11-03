#pragma once

#include <QElapsedTimer>
#include <QPushButton>
#include <QTimer>

namespace divergencesplitter::ui {

class ResetAllButton final : public QPushButton {
    Q_OBJECT

public:
    explicit ResetAllButton(QWidget* parent = nullptr);

    void set_hold_duration_ms(int duration_ms);
    [[nodiscard]] int hold_duration_ms() const noexcept { return hold_duration_ms_; }

signals:
    void holdCompleted();

protected:
    void mousePressEvent(QMouseEvent* event) override;
    void mouseReleaseEvent(QMouseEvent* event) override;
    void leaveEvent(QEvent* event) override;

private:
    void cancel_hold();
    void update_text();

    int hold_duration_ms_{2000};
    QTimer timer_;
    QElapsedTimer elapsed_;
    bool holding_{false};
};

}  // namespace divergencesplitter::ui
