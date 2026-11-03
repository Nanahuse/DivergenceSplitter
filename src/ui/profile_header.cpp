#include "profile_header.hpp"

#include <QHBoxLayout>
#include <QLabel>
#include <QLineEdit>
#include <QPushButton>

namespace divergencesplitter::ui {

ProfileHeader::ProfileHeader(QWidget* parent) : QFrame(parent) {
    setObjectName(QStringLiteral("profileHeader"));
    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(16, 10, 16, 10);
    layout->setSpacing(8);

    path_ = new QLineEdit(this);
    path_->setObjectName(QStringLiteral("profilePath"));
    path_->setReadOnly(true);
    path_->setPlaceholderText(tr("No profile selected"));
    path_->setMinimumWidth(180);
    path_->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    layout->addWidget(path_, 1);

    dirty_ = new QLabel(tr("Unsaved changes"), this);
    dirty_->setObjectName(QStringLiteral("dirtyMarker"));
    dirty_->hide();
    layout->addWidget(dirty_);

    new_ = new QPushButton(tr("New"), this);
    new_->setObjectName(QStringLiteral("profileNew"));
    open_ = new QPushButton(tr("Open"), this);
    open_->setObjectName(QStringLiteral("profileOpen"));
    save_ = new QPushButton(tr("Save"), this);
    save_->setObjectName(QStringLiteral("profileSave"));
    save_as_ = new QPushButton(tr("Save As"), this);
    save_as_->setObjectName(QStringLiteral("profileSaveAs"));
    layout->addWidget(new_);
    layout->addWidget(open_);
    layout->addWidget(save_);
    layout->addWidget(save_as_);

    connect(new_, &QPushButton::clicked, this, &ProfileHeader::newRequested);
    connect(open_, &QPushButton::clicked, this, &ProfileHeader::openRequested);
    connect(save_, &QPushButton::clicked, this, &ProfileHeader::saveRequested);
    connect(save_as_, &QPushButton::clicked, this, &ProfileHeader::saveAsRequested);

    sync(tr("No profile selected"), false, false, false);
}

void ProfileHeader::sync(
    const QString& path_text,
    bool dirty,
    bool can_save,
    bool can_save_as
) {
    if (path_->text() != path_text) {
        path_->setText(path_text);
    }
    path_->setToolTip(path_text);
    if (dirty_->isHidden() == dirty) {
        dirty_->setVisible(dirty);
    }
    save_->setEnabled(can_save);
    save_as_->setEnabled(can_save_as);
}

}  // namespace divergencesplitter::ui
