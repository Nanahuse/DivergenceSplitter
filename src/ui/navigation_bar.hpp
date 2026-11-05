#pragma once

#include <QString>
#include <QWidget>

#include <map>

class QButtonGroup;
class QToolButton;

namespace divergencesplitter::ui {

enum class AppPage {
    monitor,
    diagnostics,
    profile,
    settings,
    about,
};

class NavigationBar final : public QWidget {
    Q_OBJECT

public:
    explicit NavigationBar(QWidget* parent = nullptr);

    [[nodiscard]] AppPage current_page() const noexcept { return current_page_; }
    [[nodiscard]] bool expanded() const noexcept { return expanded_; }
    void set_current_page(AppPage page);

signals:
    void pageSelected(AppPage page);

private:
    QToolButton* add_button(AppPage page, const QString& label, int icon);
    void set_expanded(bool expanded);

    QButtonGroup* group_;
    QToolButton* toggle_;
    std::map<AppPage, QToolButton*> buttons_;
    AppPage current_page_{AppPage::monitor};
    bool expanded_{false};
};

}  // namespace divergencesplitter::ui
