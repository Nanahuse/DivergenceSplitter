#include "diagnostics_page.hpp"

#include <QColor>
#include <QHeaderView>
#include <QLabel>
#include <QScrollBar>
#include <QTreeWidget>
#include <QTreeWidgetItem>
#include <QVBoxLayout>

#include <optional>
#include <string>
#include <vector>

#include "app_controller.hpp"
#include "theme.hpp"

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
    QString column4;
    QString column5;
    QColor color;
};

QString score_text(const std::optional<double>& value) {
    return value.has_value() ? QString::number(*value, 'f', 4) : QString{};
}

QString instance_state_text(InstanceState state) {
    switch (state) {
        case InstanceState::connecting:
            return QObject::tr("Connecting");
        case InstanceState::ready:
            return QObject::tr("Ready");
        case InstanceState::failed:
            return QObject::tr("Failed");
        case InstanceState::stopped:
            return QObject::tr("Stopped");
    }
    return {};
}

QColor condition_color(const QString& status, const theme::SemanticColors& colors) {
    if (status == "true") {
        return colors.ready;
    }
    if (status == "error") {
        return colors.error;
    }
    if (status == "false") {
        return colors.warning;
    }
    return colors.muted;
}

QColor state_color(InstanceState state, const theme::SemanticColors& colors) {
    switch (state) {
        case InstanceState::ready:
            return colors.ready;
        case InstanceState::connecting:
            return colors.connecting;
        case InstanceState::failed:
            return colors.failed;
        case InstanceState::stopped:
            return colors.stopped;
    }
    return colors.muted;
}

class RowBuilder {
public:
    explicit RowBuilder(theme::SemanticColors colors) : colors_(std::move(colors)) {}

    void add(
        const QString& key,
        const QString& parent,
        QString column0,
        QString column1 = {},
        QString column2 = {},
        QString column3 = {},
        QString column4 = {},
        QString column5 = {},
        QColor color = {}
    ) {
        rows.push_back(DiagnosticRow{
            key,
            parent,
            next_position_[parent]++,
            std::move(column0),
            std::move(column1),
            std::move(column2),
            std::move(column3),
            std::move(column4),
            std::move(column5),
            std::move(color),
        });
    }

    void add_condition(
        const QString& parent,
        const ConditionDiagnosticsNode& node,
        const QString& scenario_prefix
    ) {
        const QString key = scenario_prefix + QString::fromStdString(node.path);
        const QString status = QString::fromStdString(node.status);
        const QString type = QString::fromStdString(node.type);
        const QString description = QString::fromStdString(node.description);
        add(
            key,
            parent,
            type,
            status,
            {},
            {},
            {},
            description == type ? QString{} : description,
            condition_color(status, colors_)
        );
        if (!node.detector_type.empty()) {
            add(
                key + QStringLiteral("/detector"),
                key,
                QString::fromStdString(node.detector_type),
                status,
                score_text(node.minimum_score),
                score_text(node.latest_score),
                score_text(node.max_score),
                {},
                condition_color(status, colors_)
            );
        }
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
        add(key, parent, label, {}, {}, {}, {}, active);
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
    const theme::SemanticColors& colors() const { return colors_; }

private:
    theme::SemanticColors colors_;
    QHash<QString, int> next_position_;
};

std::vector<DiagnosticRow> build_rows(
    const std::vector<InstanceDiagnosticsSnapshot>& instances
) {
    RowBuilder builder{theme::colors(theme::current_mode())};
    for (const auto& instance : instances) {
        const QString root = QStringLiteral("s%1").arg(instance.index);
        const QString prefix = root + QLatin1Char('/');
        builder.add(
            root,
            {},
            QObject::tr("Scenario %1").arg(instance.index),
            instance_state_text(instance.state),
            {},
            {},
            {},
            QString::fromStdString(instance.error),
            state_color(instance.state, builder.colors())
        );
        builder.add(
            root + QStringLiteral("/connection"),
            root,
            QObject::tr("Connection"),
            {},
            {},
            {},
            {},
            QString::fromStdString(instance.error),
            state_color(instance.state, builder.colors())
        );
        if (instance.run.has_value()) {
            builder.add(
                root + QStringLiteral("/run"),
                root,
                QObject::tr("Run"),
                {},
                {},
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
        builder.add_group(
            QObject::tr("Incomplete"), QStringLiteral("incomplete"), scenario.incomplete, prefix, root
        );

        const QString splits_key = prefix + QStringLiteral("splits");
        builder.add(splits_key, root, QObject::tr("Splits"));
        for (const auto& split : scenario.splits) {
            const QString split_key = prefix + QString::fromStdString(split.path);
            builder.add(
                split_key,
                splits_key,
                QObject::tr("Split %1").arg(split.index + 1),
                split.configured ? QObject::tr("configured") : QObject::tr("not configured")
            );
            for (const auto& rule : split.rules) {
                builder.add_rule(split_key, rule, prefix);
            }
        }
        const bool measured = scenario.evaluation_count > 0;
        builder.add(
            prefix + QStringLiteral("metrics"),
            root,
            QObject::tr("Evaluation"),
            {},
            {},
            {},
            {},
            QObject::tr("%1 evaluations | Avg %2 ms | Max %3 ms | %4 rule errors")
                .arg(scenario.evaluation_count)
                .arg(measured ? QString::number(scenario.average_evaluation_ms, 'f', 2)
                              : QStringLiteral("—"))
                .arg(measured ? QString::number(scenario.max_evaluation_ms, 'f', 2)
                              : QStringLiteral("—"))
                .arg(scenario.rule_errors)
        );
    }
    return builder.rows;
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
    item->setText(4, row.column4);
    item->setText(5, row.column5);
    if (row.color.isValid()) {
        item->setForeground(1, row.color);
    } else {
        item->setData(1, Qt::ForegroundRole, {});
    }
}

}  // namespace

DiagnosticsPage::DiagnosticsPage(AppController* controller, QWidget* parent)
    : QWidget(parent), controller_(controller) {
    setObjectName(QStringLiteral("page"));
    auto* layout = new QVBoxLayout(this);
    layout->setContentsMargins(16, 14, 16, 14);
    layout->setSpacing(8);
    auto* title = new QLabel(tr("Diagnostics"), this);
    title->setObjectName(QStringLiteral("pageTitle"));
    layout->addWidget(title);
    auto* hint = new QLabel(
        tr("Scenario → Rule → Condition → Detector. Expand a scenario to inspect scores."),
        this
    );
    hint->setProperty("role", QStringLiteral("muted"));
    layout->addWidget(hint);

    tree_ = new QTreeWidget(this);
    tree_->setObjectName(QStringLiteral("diagnosticsTree"));
    tree_->setColumnCount(6);
    tree_->setHeaderLabels(
        {tr("Item"), tr("Status"), tr("Threshold"), tr("Current"), tr("Max"), tr("Detail")}
    );
    tree_->header()->setStretchLastSection(true);
    tree_->setAlternatingRowColors(false);
    tree_->setUniformRowHeights(true);
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
    const int scroll_position = tree_->verticalScrollBar()->value();

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
        for (int column = 0; column < 5; ++column) {
            tree_->resizeColumnToContents(column);
        }
    } else {
        for (const auto& row : rows) {
            if (auto* item = items_.value(row.key, nullptr); item != nullptr) {
                set_columns(item, row);
            }
        }
    }
    tree_->setUpdatesEnabled(true);
    if (rebuild) {
        tree_->verticalScrollBar()->setValue(scroll_position);
    }
    tree_->viewport()->update();
}

}  // namespace divergencesplitter::ui
