#include "divergencesplitter/ui/diagnostics_page.hpp"

#include <QHeaderView>
#include <QLabel>
#include <QTreeWidget>
#include <QTreeWidgetItem>
#include <QVBoxLayout>

#include <algorithm>

#include "divergencesplitter/ui/app_controller.hpp"

namespace divergencesplitter::ui {
namespace {

QString score_text(const std::optional<double>& latest, const std::optional<double>& maximum) {
    if (!latest.has_value() && !maximum.has_value()) {
        return {};
    }
    QString text;
    if (latest.has_value()) {
        text = QString::number(*latest, 'f', 4);
    } else {
        text = QStringLiteral("-");
    }
    if (maximum.has_value()) {
        text += QStringLiteral(" (max %1)").arg(*maximum, 0, 'f', 4);
    }
    return text;
}

QString instance_state_text(InstanceState state) {
    switch (state) {
        case InstanceState::connecting:
            return QObject::tr("connecting");
        case InstanceState::ready:
            return QObject::tr("ready");
        case InstanceState::failed:
            return QObject::tr("failed");
        case InstanceState::stopped:
            return QObject::tr("stopped");
    }
    return {};
}

}  // namespace

DiagnosticsPage::DiagnosticsPage(AppController* controller, QWidget* parent)
    : QWidget(parent), controller_(controller) {
    auto* layout = new QVBoxLayout(this);
    auto* title = new QLabel(tr("Diagnostics"), this);
    QFont title_font = title->font();
    title_font.setPointSize(title_font.pointSize() + 4);
    title_font.setBold(true);
    title->setFont(title_font);
    layout->addWidget(title);

    tree_ = new QTreeWidget(this);
    tree_->setColumnCount(4);
    tree_->setHeaderLabels({tr("Item"), tr("Status"), tr("Score"), tr("Detail")});
    tree_->header()->setStretchLastSection(true);
    tree_->setAlternatingRowColors(true);
    layout->addWidget(tree_, 1);
}

void DiagnosticsPage::refresh() {
    QSet<QString> expanded;
    for (int index = 0; index < tree_->topLevelItemCount(); ++index) {
        collect_expanded(tree_->topLevelItem(index), expanded);
    }
    tree_->clear();

    const auto instances = controller_->session().instance_diagnostics();
    for (const auto& instance : instances) {
        auto* scenario_item = new QTreeWidgetItem(tree_);
        scenario_item->setText(0, tr("Scenario %1").arg(instance.index));
        scenario_item->setText(1, instance_state_text(instance.state));
        scenario_item->setText(3, QString::fromStdString(instance.error));
        scenario_item->setData(0, Qt::UserRole, QStringLiteral("scenario:%1").arg(instance.index));

        if (instance.run.has_value()) {
            auto* run_item = new QTreeWidgetItem(scenario_item);
            run_item->setText(0, tr("Run"));
            run_item->setText(3, QString::fromStdString(instance.run->segments.empty()
                ? std::string{"no segments"}
                : instance.run->segments.front().name));
        }

        if (!instance.scenario.has_value()) {
            continue;
        }
        const auto& scenario = *instance.scenario;
        const auto add_group = [&](const QString& name,
                                   const std::vector<RuleGroupDiagnostics>& groups) {
            auto* group_item = new QTreeWidgetItem(scenario_item);
            group_item->setText(0, name);
            for (const auto& group : groups) {
                for (const auto& rule : group.rules) {
                    make_rule_item(group_item, rule);
                }
            }
        };
        add_group(tr("Start"), scenario.start);
        add_group(tr("Reset"), scenario.reset);
        add_group(tr("Incomplete"), scenario.incomplete);

        auto* splits_item = new QTreeWidgetItem(scenario_item);
        splits_item->setText(0, tr("Splits"));
        for (const auto& split : scenario.splits) {
            auto* split_item = new QTreeWidgetItem(splits_item);
            split_item->setText(0, tr("Split %1").arg(split.index));
            split_item->setText(1, split.configured ? tr("configured") : tr("not configured"));
            for (const auto& rule : split.rules) {
                make_rule_item(split_item, rule);
            }
        }
        auto* metrics_item = new QTreeWidgetItem(scenario_item);
        metrics_item->setText(0, tr("Evaluation"));
        metrics_item->setText(3,
            tr("%1 evaluations, %2 ms last, %3 rule errors")
                .arg(scenario.evaluation_count)
                .arg(scenario.last_evaluation_ms, 0, 'f', 3)
                .arg(scenario.rule_errors));
    }

    for (int index = 0; index < tree_->topLevelItemCount(); ++index) {
        restore_expanded(tree_->topLevelItem(index), expanded);
    }
    tree_->resizeColumnToContents(0);
    tree_->resizeColumnToContents(1);
    tree_->resizeColumnToContents(2);
}

QTreeWidgetItem* DiagnosticsPage::make_condition_item(
    QTreeWidgetItem* parent,
    const ConditionDiagnosticsNode& node
) const {
    auto* item = new QTreeWidgetItem(parent);
    item->setText(0, QString::fromStdString(node.type));
    item->setText(1, QString::fromStdString(node.status));
    item->setText(2, score_text(node.latest_score, node.max_score));
    QString detail = QString::fromStdString(node.description);
    if (!node.detector_type.empty()) {
        detail += QStringLiteral(" [%1]").arg(QString::fromStdString(node.detector_type));
    }
    if (node.minimum_score.has_value()) {
        detail += QStringLiteral(" threshold=%1").arg(*node.minimum_score);
    }
    item->setText(3, detail);
    item->setData(0, Qt::UserRole, QString::fromStdString(node.type) + detail);
    for (const auto& child : node.children) {
        make_condition_item(item, child);
    }
    return item;
}

QTreeWidgetItem* DiagnosticsPage::make_rule_item(
    QTreeWidgetItem* parent,
    const RuleDiagnosticsNode& node
) const {
    auto* item = new QTreeWidgetItem(parent);
    const QString type = QString::fromStdString(node.type);
    if (node.action.has_value()) {
        item->setText(0, tr("Rule %1 -> %2")
            .arg(node.index)
            .arg(QString::fromStdString(std::string{to_string(*node.action)})));
    } else {
        item->setText(0, type);
    }
    if (node.active_rule_index.has_value()) {
        item->setText(3, tr("active step %1").arg(*node.active_rule_index));
    }
    item->setData(0, Qt::UserRole,
        QStringLiteral("%1:%2:%3").arg(type).arg(node.index).arg(
            node.active_rule_index.value_or(0)));
    if (node.condition.type != "none" && !node.condition.type.empty()) {
        make_condition_item(item, node.condition);
    }
    for (const auto& rule : node.sequence_rules) {
        make_rule_item(item, rule);
    }
    return item;
}

void DiagnosticsPage::collect_expanded(QTreeWidgetItem* item, QSet<QString>& keys) const {
    if (item->isExpanded()) {
        keys.insert(item->data(0, Qt::UserRole).toString());
    }
    for (int index = 0; index < item->childCount(); ++index) {
        collect_expanded(item->child(index), keys);
    }
}

void DiagnosticsPage::restore_expanded(QTreeWidgetItem* item, const QSet<QString>& keys) {
    if (keys.contains(item->data(0, Qt::UserRole).toString())) {
        item->setExpanded(true);
    }
    for (int index = 0; index < item->childCount(); ++index) {
        restore_expanded(item->child(index), keys);
    }
}

}  // namespace divergencesplitter::ui
