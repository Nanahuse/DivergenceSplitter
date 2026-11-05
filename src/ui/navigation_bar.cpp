#include "navigation_bar.hpp"

#include <QButtonGroup>
#include <QFont>
#include <QStyle>
#include <QToolButton>
#include <QVBoxLayout>

namespace divergencesplitter::ui {
namespace {

constexpr int kCollapsedWidth = 60;
constexpr int kExpandedWidth = 180;

}  // namespace

NavigationBar::NavigationBar(QWidget* parent) : QWidget(parent), group_(new QButtonGroup(this)) {
    setObjectName(QStringLiteral("navPanel"));
    setFixedWidth(kCollapsedWidth);
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(8, 8, 8, 8);
    layout->setSpacing(4);

    toggle_ = new QToolButton(this);
    toggle_->setObjectName(QStringLiteral("navToggle"));
    toggle_->setText(QString(QChar(0x203A)));
    QFont toggle_font = toggle_->font();
    toggle_font.setPointSize(toggle_font.pointSize() + 4);
    toggle_->setFont(toggle_font);
    toggle_->setToolButtonStyle(Qt::ToolButtonTextOnly);
    toggle_->setToolTip(tr("Expand navigation"));
    toggle_->setAutoRaise(true);
    toggle_->setFixedHeight(38);
    connect(toggle_, &QToolButton::clicked, this, [this] { set_expanded(!expanded_); });
    layout->addWidget(toggle_);

    add_button(AppPage::monitor, tr("Monitor"), QStyle::SP_ComputerIcon);
    add_button(AppPage::diagnostics, tr("Diagnostics"), QStyle::SP_FileDialogDetailedView);
    add_button(AppPage::profile, tr("Profile"), QStyle::SP_FileIcon);
    layout->addStretch(1);
    add_button(AppPage::settings, tr("Settings"), QStyle::SP_FileDialogContentsView);
    add_button(AppPage::about, tr("About"), QStyle::SP_MessageBoxInformation);

    set_current_page(AppPage::monitor);
    set_expanded(false);
}

QToolButton* NavigationBar::add_button(AppPage page, const QString& label, int icon) {
    auto* button = new QToolButton(this);
    button->setObjectName(QStringLiteral("navButton"));
    button->setCheckable(true);
    button->setAutoRaise(true);
    button->setIcon(style()->standardIcon(static_cast<QStyle::StandardPixmap>(icon)));
    button->setIconSize(QSize(20, 20));
    button->setToolButtonStyle(Qt::ToolButtonIconOnly);
    button->setText(label);
    button->setToolTip(label);
    button->setFixedHeight(40);
    button->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    connect(button, &QToolButton::clicked, this, [this, page] {
        set_current_page(page);
        emit pageSelected(page);
    });
    group_->addButton(button);
    buttons_[page] = button;
    auto* layout = qobject_cast<QVBoxLayout*>(this->layout());
    layout->addWidget(button);
    return button;
}

void NavigationBar::set_current_page(AppPage page) {
    current_page_ = page;
    if (const auto found = buttons_.find(page); found != buttons_.end()) {
        found->second->setChecked(true);
    }
}

void NavigationBar::set_expanded(bool expanded) {
    expanded_ = expanded;
    setFixedWidth(expanded ? kExpandedWidth : kCollapsedWidth);
    toggle_->setText(QString(QChar(expanded ? 0x2039 : 0x203A)));
    toggle_->setToolTip(expanded ? tr("Collapse navigation") : tr("Expand navigation"));
    for (const auto& [page, button] : buttons_) {
        Q_UNUSED(page);
        button->setToolButtonStyle(
            expanded ? Qt::ToolButtonTextBesideIcon : Qt::ToolButtonIconOnly
        );
        button->setToolTip(expanded ? QString{} : button->text());
        button->update();
    }
}

}  // namespace divergencesplitter::ui
