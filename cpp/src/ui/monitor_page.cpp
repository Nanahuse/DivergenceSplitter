#include "divergencesplitter/ui/monitor_page.hpp"

#include <QHeaderView>
#include <QLabel>
#include <QTableWidget>
#include <QVBoxLayout>
#include <QStringList>

#include "divergencesplitter/ui/app_controller.hpp"
#include "divergencesplitter/ui/image_view.hpp"
#include "divergencesplitter/ui/reset_all_button.hpp"

namespace divergencesplitter::ui {
namespace {

QString state_text(InstanceState state) {
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

QString phase_text(TimerPhase phase) {
    switch (phase) {
        case TimerPhase::not_running:
            return QObject::tr("Not running");
        case TimerPhase::running:
            return QObject::tr("Running");
        case TimerPhase::paused:
            return QObject::tr("Paused");
        case TimerPhase::ended:
            return QObject::tr("Ended");
        case TimerPhase::unspecified:
            return QObject::tr("Unknown");
    }
    return {};
}

QString split_text(const InstanceDiagnosticsSnapshot& instance) {
    if (!instance.scenario.has_value() || !instance.scenario->snapshot.has_value()) {
        return {};
    }
    const auto& snapshot = *instance.scenario->snapshot;
    if (snapshot.split_count <= 0) {
        return QString::number(snapshot.split_index);
    }
    return QStringLiteral("%1 / %2")
        .arg(std::max(0, snapshot.split_index))
        .arg(snapshot.split_count);
}

void collect_detector_summaries(const ConditionDiagnosticsNode& node, QStringList& scores) {
    if (!node.detector_type.empty() && node.status != "skipped" && node.status != "not_evaluated") {
        QString text = QString::fromStdString(node.detector_type);
        if (node.latest_score) text += QObject::tr(" score %1").arg(*node.latest_score, 0, 'f', 3);
        if (node.minimum_score) text += QObject::tr(" ≥ %1").arg(*node.minimum_score, 0, 'f', 3);
        scores.append(text);
    }
    for (const auto& child : node.children) collect_detector_summaries(child, scores);
}

void append_condition(const ConditionDiagnosticsNode& node, QStringList& lines) {
    if (node.type == "none") return;
    QString text = QString::fromStdString(node.path + ": " +
        (node.description.empty() || !node.detector_type.empty() ? node.type : node.description) +
        " [" + node.status + "]");
    QStringList scores;
    collect_detector_summaries(node, scores);
    if (!scores.isEmpty()) text += QStringLiteral(" | ") + scores.mid(0, 2).join(QStringLiteral("; "));
    if (scores.size() > 2) text += QObject::tr(" (+%1 detectors; see Diagnostics)").arg(scores.size() - 2);
    lines.append(text);
}

void append_rule(const RuleDiagnosticsNode& rule, QStringList& lines) {
    if (!rule.sequence_rules.empty()) {
        if (rule.active_rule_index && *rule.active_rule_index < rule.sequence_rules.size())
            append_rule(rule.sequence_rules[*rule.active_rule_index], lines);
        return;
    }
    append_condition(rule.condition, lines);
}

}  // namespace

QString scenario_overview(const ScenarioDiagnosticsSnapshot& scenario) {
    if (!scenario.configuration_valid) return QObject::tr("Scenario / split count mismatch");
    if (!scenario.snapshot) return QObject::tr("Waiting for timer state");
    QStringList lines;
    const auto append_groups = [&](const std::vector<RuleGroupDiagnostics>& groups) {
        for (const auto& group : groups)
            for (const auto& rule : group.rules) append_rule(rule, lines);
    };
    if (scenario.reset_pending) {
        return QObject::tr("Waiting for Reset confirmation");
    }
    if (scenario.pending_action) {
        lines.append(QObject::tr("Pending: %1")
            .arg(QString::fromStdString(std::string{to_string(*scenario.pending_action)})));
    }
    const auto& snapshot = *scenario.snapshot;
    if (snapshot.phase == TimerPhase::not_running) append_groups(scenario.start);
    else if (snapshot.phase == TimerPhase::ended) append_groups(scenario.incomplete);
    else if (snapshot.phase == TimerPhase::running || snapshot.phase == TimerPhase::paused) {
        append_groups(scenario.reset);
        if (!scenario.pending_action && snapshot.split_index >= 0 &&
            static_cast<std::size_t>(snapshot.split_index) < scenario.splits.size()) {
            for (const auto& rule : scenario.splits[static_cast<std::size_t>(snapshot.split_index)].rules)
                append_rule(rule, lines);
        }
    }
    return lines.isEmpty() ? QObject::tr("No condition configured") : lines.join('\n');
}

MonitorPage::MonitorPage(AppController* controller, QWidget* parent)
    : QWidget(parent), controller_(controller) {
    connect(controller_, &AppController::sessionStarting, this, [this] { evaluation_rates_.clear(); });
    auto* layout = new QVBoxLayout(this);

    auto* title = new QLabel(tr("Monitor"), this);
    QFont title_font = title->font();
    title_font.setPointSize(title_font.pointSize() + 4);
    title_font.setBold(true);
    title->setFont(title_font);
    layout->addWidget(title);

    preview_ = new ImageView(this);
    layout->addWidget(preview_, 1);

    capture_label_ = new QLabel(tr("Input: stopped"), this);
    layout->addWidget(capture_label_);

    instance_table_ = new QTableWidget(this);
    instance_table_->setObjectName(QStringLiteral("monitorInstances"));
    instance_table_->setColumnCount(8);
    instance_table_->setHorizontalHeaderLabels(
        {tr("Scenario"), tr("State"), tr("Phase"), tr("Split"), tr("Last action"), tr("Detail"),
         tr("Processing FPS"), tr("Current evaluation")}
    );
    instance_table_->horizontalHeader()->setStretchLastSection(true);
    instance_table_->verticalHeader()->setVisible(false);
    instance_table_->setEditTriggers(QAbstractItemView::NoEditTriggers);
    instance_table_->setSelectionBehavior(QAbstractItemView::SelectRows);
    layout->addWidget(instance_table_, 1);

    error_label_ = new QLabel(this);
    error_label_->setWordWrap(true);
    error_label_->setStyleSheet("color: #b00020;");
    layout->addWidget(error_label_);

    reset_button_ = new ResetAllButton(this);
    layout->addWidget(reset_button_);
    connect(reset_button_, &ResetAllButton::holdCompleted, this, &MonitorPage::resetRequested);
}

void MonitorPage::refresh() {
    const auto preview = controller_->session().latest_preview();
    if (preview && !preview->empty()) {
        preview_->set_image(mat_to_qimage(*preview));
    } else {
        preview_->clear();
    }

    const auto capture = controller_->session().capture_stats();
    capture_label_->setText(
        tr("Input: %1 frames, %2 fps  |  %3")
            .arg(capture.frames_published)
            .arg(capture.measured_fps, 0, 'f', 1)
            .arg(capture.running ? tr("running") : tr("stopped"))
    );

    const auto instances = controller_->session().instance_diagnostics();
    if (instances.empty()) evaluation_rates_.clear();
    instance_table_->setRowCount(static_cast<int>(instances.size()));
    for (int row = 0; row < static_cast<int>(instances.size()); ++row) {
        const auto& instance = instances[static_cast<std::size_t>(row)];
        const QString detail = !instance.error.empty()
            ? QString::fromStdString(instance.error)
            : instance.last_action_result.empty()
                ? QString{}
                : QString::fromStdString(instance.last_action_result);
        const auto set = [&](int column, const QString& text) {
            auto* item = instance_table_->item(row, column);
            if (item == nullptr) {
                item = new QTableWidgetItem;
                instance_table_->setItem(row, column, item);
            }
            item->setText(text);
        };
        set(0, tr("Scenario %1").arg(instance.index));
        set(1, state_text(instance.state));
        set(2, instance.scenario.has_value() && instance.scenario->snapshot.has_value()
                   ? phase_text(instance.scenario->snapshot->phase)
                   : QString{});
        set(3, split_text(instance));
        set(4, instance.last_action.has_value()
                   ? QString::fromStdString(std::string{to_string(*instance.last_action)})
                   : QString{});
        set(5, detail);
        const auto count = instance.scenario ? instance.scenario->evaluation_count : 0;
        const auto now = std::chrono::steady_clock::now();
        auto [rate_it, inserted] = evaluation_rates_.try_emplace(instance.index,
            EvaluationRate{instance.generation, count, now, 0.0});
        auto& rate = rate_it->second;
        if (rate.generation != instance.generation || count < rate.count) {
            rate = EvaluationRate{instance.generation, count, now, 0.0};
        }
        const double elapsed = std::chrono::duration<double>(now - rate.sampled_at).count();
        if (!inserted && elapsed >= 0.5) {
            rate.fps = static_cast<double>(count - rate.count) / elapsed;
            rate.count = count;
            rate.sampled_at = now;
        }
        set(6, QString::number(rate.fps, 'f', 1));
        const auto overview = instance.scenario ? scenario_overview(*instance.scenario) : QString{};
        set(7, overview.section('\n', 0, 2));
        instance_table_->item(row, 7)->setToolTip(overview + tr("\nFull condition tree and maxima: Diagnostics"));
    }
    for (int column = 0; column < 7; ++column) instance_table_->resizeColumnToContents(column);
    instance_table_->resizeRowsToContents();

    const QString runtime_error = controller_->last_error();
    error_label_->setText(runtime_error);
    error_label_->setVisible(!runtime_error.isEmpty());
}

}  // namespace divergencesplitter::ui
