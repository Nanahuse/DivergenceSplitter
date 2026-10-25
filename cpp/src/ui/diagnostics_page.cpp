#include "divergencesplitter/ui/diagnostics_page.hpp"

#include <QHeaderView>
#include <QLabel>
#include <QTreeWidget>
#include <QTreeWidgetItem>
#include <QVBoxLayout>

#include <optional>
#include <string>
#include <vector>

#include "divergencesplitter/ui/app_controller.hpp"

namespace divergencesplitter::ui {
namespace {

struct DiagnosticRow {
    QString key;
    QString parent;
    int position{};
    QString column0;
    QString column1;
    QString column2;
    QString column3;
};

QString score_text(const std::optional<double>& latest, const std::optional<double>& maximum) {
    if (!latest.has_value() && !maximum.has_value()) {
        return {};
    }
    QString text = latest.has_value() ? QString::number(*latest, 'f', 4) : QStringLiteral("-");
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

QString condition_detail(const ConditionDiagnosticsNode& node) {
    QString detail = QString::fromStdString(node.description);
    if (!node.detector_type.empty()) {
        detail += QStringLiteral(" [%1]").arg(QString::fromStdString(node.detector_type));
    }
    if (node.minimum_score.has_value()) {
        detail += QStringLiteral(" threshold=%1").arg(*node.minimum_score);
    }
    return detail;
}

class RowBuilder {
public:
    void add(
        const QString& key,
        const QString& parent,
        QString column0,
        QString column1 = {},
        QString column2 = {},
        QString column3 = {}
    ) {
        rows.push_back(DiagnosticRow{
            key,
            parent,
            next_position_[parent]++,
            std::move(column0),
            std::move(column1),
            std::move(column2),
            std::move(column3),
        });
    }

    void add_condition(
        const QString& parent,
        const ConditionDiagnosticsNode& node,
        const QString& scenario_prefix
    ) {
        const QString key = scenario_prefix + QString::fromStdString(node.path);
        add(
            key,
            parent,
            QString::fromStdString(node.type),
            QString::fromStdString(node.status),
            score_text(node.latest_score, node.max_score),
            condition_detail(node)
        );
        for (const auto& child : node.children) {
            add_condition(key, child, scenario_prefix);
        }
    }

    void add_rule(
        const QString& parent,
        const RuleDiagnosticsNode& node,
        const QString& scenario_prefix
    ) {
        const QString key = scenario_prefix + QString::fromStdString(node.path);
        QString label = QString::fromStdString(node.type);
        if (node.action.has_value()) {
            label = QObject::tr("Rule %1 -> %2")
                        .arg(node.index)
                        .arg(QString::fromStdString(std::string{to_string(*node.action)}));
        }
        const QString active = node.active_rule_index.has_value()
            ? QObject::tr("active step %1").arg(*node.active_rule_index)
            : QString{};
        add(key, parent, label, {}, {}, active);
        if (node.condition.type != "none" && !node.condition.type.empty()) {
            add_condition(key, node.condition, scenario_prefix);
        }
        for (const auto& rule : node.sequence_rules) {
            add_rule(key, rule, scenario_prefix);
        }
    }

    void add_group(
        const QString& name,
        const QString& path,
        const std::vector<RuleGroupDiagnostics>& groups,
        const QString& scenario_prefix,
        const QString& parent
    ) {
        const QString key = scenario_prefix + path;
        add(key, parent, name);
        for (const auto& group : groups) {
            for (const auto& rule : group.rules) {
                add_rule(key, rule, scenario_prefix);
            }
        }
    }

    std::vector<DiagnosticRow> rows;

private:
    QHash<QString, int> next_position_;
};

std::vector<DiagnosticRow> build_rows(
    const std::vector<InstanceDiagnosticsSnapshot>& instances
) {
    RowBuilder builder;
    for (const auto& instance : instances) {
        const QString root = QStringLiteral("s%1").arg(instance.index);
        const QString prefix = root + QLatin1Char('/');
        builder.add(
            root,
            {},
            QObject::tr("Scenario %1").arg(instance.index),
            instance_state_text(instance.state),
            {},
            QString::fromStdString(instance.error)
        );
        if (instance.run.has_value()) {
            builder.add(
                root + QStringLiteral("/run"),
                root,
                QObject::tr("Run"),
                {},
                {},
                QString::fromStdString(
                    instance.run->segments.empty() ? std::string{"no segments"}
                                                   : instance.run->segments.front().name
                )
            );
        }
        if (!instance.scenario.has_value()) {
            continue;
        }
        const auto& scenario = *instance.scenario;
        builder.add_group(QObject::tr("Start"), QStringLiteral("start"), scenario.start, prefix, root);
        builder.add_group(QObject::tr("Reset"), QStringLiteral("reset"), scenario.reset, prefix, root);
        builder.add_group(QObject::tr("Incomplete"), QStringLiteral("incomplete"), scenario.incomplete, prefix, root);

        const QString splits_key = prefix + QStringLiteral("splits");
        builder.add(splits_key, root, QObject::tr("Splits"));
        for (const auto& split : scenario.splits) {
            const QString split_key = prefix + QString::fromStdString(split.path);
            builder.add(
                split_key,
                splits_key,
                QObject::tr("Split %1").arg(split.index),
                split.configured ? QObject::tr("configured") : QObject::tr("not configured")
            );
            for (const auto& rule : split.rules) {
                builder.add_rule(split_key, rule, prefix);
            }
        }
        builder.add(
            prefix + QStringLiteral("metrics"),
            root,
            QObject::tr("Evaluation"),
            {},
            {},
            QObject::tr("%1 evaluations, %2 ms last, %3 rule errors")
                .arg(scenario.evaluation_count)
                .arg(scenario.last_evaluation_ms, 0, 'f', 3)
                .arg(scenario.rule_errors)
        );
    }
    return std::move(builder.rows);
}

QString signature_of(const std::vector<DiagnosticRow>& rows) {
    QString signature;
    signature.reserve(static_cast<int>(rows.size() * 48));
    for (const auto& row : rows) {
        signature += row.key;
        signature += QLatin1Char('|');
        signature += row.parent;
        signature += QLatin1Char('|');
        signature += QString::number(row.position);
        signature += QLatin1Char('\n');
    }
    return signature;
}

void collect_state(
    QTreeWidgetItem* item,
    QSet<QString>& expanded,
    QString& selected_key
) {
    const QString key = item->data(0, Qt::UserRole).toString();
    if (item->isExpanded()) {
        expanded.insert(key);
    }
    if (item->isSelected()) {
        selected_key = key;
    }
    for (int index = 0; index < item->childCount(); ++index) {
        collect_state(item->child(index), expanded, selected_key);
    }
}

void set_columns(QTreeWidgetItem* item, const DiagnosticRow& row) {
    item->setText(0, row.column0);
    item->setText(1, row.column1);
    item->setText(2, row.column2);
    item->setText(3, row.column3);
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
    const auto instances = controller_->session().instance_diagnostics();
    const auto rows = build_rows(instances);
    const QString signature = signature_of(rows);

    QSet<QString> expanded;
    QString selected_key;
    for (int index = 0; index < tree_->topLevelItemCount(); ++index) {
        collect_state(tree_->topLevelItem(index), expanded, selected_key);
    }

    tree_->setUpdatesEnabled(false);
    const bool rebuild = signature != structure_signature_ ||
                         items_.size() != static_cast<int>(rows.size());
    if (rebuild) {
        const bool first_build = structure_signature_.isEmpty();
        tree_->clear();
        items_.clear();
        for (const auto& row : rows) {
            QTreeWidgetItem* parent = row.parent.isEmpty()
                ? nullptr
                : items_.value(row.parent, nullptr);
            auto* item = parent != nullptr
                ? new QTreeWidgetItem(parent)
                : new QTreeWidgetItem(tree_);
            item->setData(0, Qt::UserRole, row.key);
            set_columns(item, row);
            items_.insert(row.key, item);
            if (first_build && row.parent.isEmpty()) {
                item->setExpanded(true);
            } else if (expanded.contains(row.key)) {
                item->setExpanded(true);
            }
        }
        structure_signature_ = signature;
        if (!selected_key.isEmpty() && items_.contains(selected_key)) {
            tree_->setCurrentItem(items_.value(selected_key));
        }
        tree_->resizeColumnToContents(0);
        tree_->resizeColumnToContents(1);
        tree_->resizeColumnToContents(2);
    } else {
        for (const auto& row : rows) {
            if (auto* item = items_.value(row.key, nullptr); item != nullptr) {
                set_columns(item, row);
            }
        }
    }
    tree_->setUpdatesEnabled(true);
    tree_->viewport()->update();
}

}  // namespace divergencesplitter::ui