#pragma once

#include <QWidget>

class QLabel;
class QTableWidget;

namespace divergencesplitter::ui {

class AppController;
class ImageView;
class ResetAllButton;

class MonitorPage final : public QWidget {
    Q_OBJECT

public:
    explicit MonitorPage(AppController* controller, QWidget* parent = nullptr);

    void refresh();

signals:
    void resetRequested();

private:
    AppController* controller_;
    ImageView* preview_;
    QLabel* capture_label_;
    QLabel* error_label_;
    QTableWidget* instance_table_;
    ResetAllButton* reset_button_;
};

}  // namespace divergencesplitter::ui
