#pragma once

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
    void collect_expanded(QTreeWidgetItem* item, QSet<QString>& keys) const;
    void restore_expanded(QTreeWidgetItem* item, const QSet<QString>& keys);
    QTreeWidgetItem* make_condition_item(
        QTreeWidgetItem* parent,
        const ConditionDiagnosticsNode& node
    ) const;
    QTreeWidgetItem* make_rule_item(
        QTreeWidgetItem* parent,
        const RuleDiagnosticsNode& node
    ) const;

    AppController* controller_;
    QTreeWidget* tree_;
};

}  // namespace divergencesplitter::ui
