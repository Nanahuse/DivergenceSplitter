#pragma once

#include <QFrame>

class QLabel;
class QLineEdit;
class QPushButton;

namespace divergencesplitter::ui {

class ProfileHeader final : public QFrame {
    Q_OBJECT

public:
    explicit ProfileHeader(QWidget* parent = nullptr);

    void sync(const QString& path_text, bool dirty, bool can_save, bool can_save_as);

signals:
    void newRequested();
    void openRequested();
    void saveRequested();
    void saveAsRequested();

private:
    QLineEdit* path_;
    QLabel* dirty_;
    QPushButton* new_;
    QPushButton* open_;
    QPushButton* save_;
    QPushButton* save_as_;
};

}  // namespace divergencesplitter::ui
