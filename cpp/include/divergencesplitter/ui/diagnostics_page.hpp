#pragma once

#include <QHash>
#include <QSet>
#include <QString>
#include <QWidget>

#include "divergencesplitter/runtime/diagnostics.hpp"

class QTreeWidget;
class QTreeWidgetItem;

namespace divergencesplitter::ui {

class AppController;

class DiagnosticsPage final : public QWidget {
    Q_OBJECT

public:
    explicit DiagnosticsPage(AppController* controller, QWidget* parent = nullptr);

    void refresh();

private:
    AppController* controller_;
    QTreeWidget* tree_;
    QHash<QString, QTreeWidgetItem*> items_;
    QString structure_signature_;
};

}  // namespace divergencesplitter::ui
