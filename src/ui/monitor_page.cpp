#include "monitor_page.hpp"

#include <QFrame>
#include <QHBoxLayout>
#include <QLabel>
#include <QScrollArea>
#include <QScrollBar>
#include <QStringList>
#include <QVBoxLayout>

#include <algorithm>
#include <optional>

#include "app_controller.hpp"
#include "image_view.hpp"
#include "reset_all_button.hpp"
#include "theme.hpp"

namespace divergencesplitter::ui {
namespace {

constexpr int kIndent = 14;

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

QString score_text(const std::optional<double>& value) {
    return value.has_value() ? QString::number(*value, 'f', 4) : QStringLiteral("-");
}

QString latency_text(double milliseconds, bool measured) {
    return measured ? QStringLiteral("%1 ms").arg(milliseconds, 0, 'f', 2)
                    : QStringLiteral("-");
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

QString segment_name(const InstanceDiagnosticsSnapshot& instance, std::size_t index) {
    if (!instance.run.has_value()) {
        return {};
    }
    for (const auto& segment : instance.run->segments) {
        if (segment.index == static_cast<int>(index)) {
            return QString::fromStdString(segment.name);
        }
    }
    return {};
}

QString condition_detail(const ConditionDiagnosticsNode& node) {
    if (!node.detector_type.empty()) {
        QString detail = QStringLiteral("%1   %2 / %3   Max: %4")
            .arg(QString::fromStdString(node.detector_type))
            .arg(score_text(node.latest_score))
            .arg(score_text(node.minimum_score))
            .arg(score_text(node.max_score));
        if (node.status == "error") {
            detail.prepend(QObject::tr("ERROR   "));
        }
        return detail;
    }
    if (!node.description.empty() && node.description != node.type) {
        return QString::fromStdString(node.description);
    }
    return {};
}

struct EvaluationLine {
    QString label;
    QString detail;
    int depth{};
    bool strong{};
};

struct EvaluationGroup {
    QString label;
    std::vector<EvaluationLine> lines;
};

struct CardData {
    int index{};
    InstanceState state{InstanceState::connecting};
    bool has_state{};
    QString status;
    QString error;
    std::vector<EvaluationGroup> groups;
    QString average;
    QString maximum;
};

bool is_visible_condition(const ConditionDiagnosticsNode& node) {
    if (node.type.empty() || node.type == "none") {
        return false;
    }
    if (node.status == "true" || node.status == "false" || node.status == "error") {
        return true;
    }
    return std::any_of(node.children.begin(), node.children.end(), is_visible_condition);
}

void append_condition(
    const ConditionDiagnosticsNode& node,
    int depth,
    std::vector<EvaluationLine>& lines
) {
    if (node.type.empty() || node.type == "none") {
        for (const auto& child : node.children) {
            append_condition(child, depth, lines);
        }
        return;
    }
    if (node.status == "true" || node.status == "false" || node.status == "error") {
        QString label = QString::fromStdString(node.type);
        if (!node.status.empty()) {
            label += QStringLiteral(" [%1]").arg(QString::fromStdString(node.status));
        }
        lines.push_back(EvaluationLine{label, condition_detail(node), depth, false});
    }
    for (const auto& child : node.children) {
        append_condition(child, depth + 1, lines);
    }
}

void append_rules(
    const std::vector<RuleDiagnosticsNode>& rules,
    int depth,
    std::vector<EvaluationLine>& lines
) {
    for (const auto& rule : rules) {
        if (!rule.sequence_rules.empty()) {
            if (rule.active_rule_index.has_value() &&
                *rule.active_rule_index < rule.sequence_rules.size()) {
                append_rules(
                    {rule.sequence_rules[*rule.active_rule_index]}, depth, lines
                );
            }
            continue;
        }
        QString label = QObject::tr("Rule %1").arg(rule.index);
        if (rule.action.has_value()) {
            label += QStringLiteral(" -> %1")
                         .arg(QString::fromStdString(
                             std::string{to_string(*rule.action)}
                         ));
        }
        lines.push_back(EvaluationLine{label, {}, depth, true});
        if (is_visible_condition(rule.condition)) {
            append_condition(rule.condition, depth + 1, lines);
        }
    }
}

void append_group(
    const std::vector<RuleGroupDiagnostics>& groups,
    const QString& label,
    int depth,
    std::vector<EvaluationGroup>& result
) {
    EvaluationGroup group;
    group.label = label;
    for (const auto& source : groups) {
        append_rules(source.rules, depth + 1, group.lines);
    }
    if (!group.lines.empty()) {
        result.push_back(std::move(group));
    }
}

std::vector<EvaluationGroup> evaluation_groups(
    const InstanceDiagnosticsSnapshot& instance
) {
    std::vector<EvaluationGroup> result;
    if (!instance.scenario.has_value()) {
        return result;
    }
    const auto& scenario = *instance.scenario;
    if (!scenario.configuration_valid) {
        result.push_back(
            EvaluationGroup{QString{}, {EvaluationLine{
                QObject::tr("Scenario / split count mismatch"), {}, 0, false}}}
        );
        return result;
    }
    if (!scenario.snapshot.has_value()) {
        result.push_back(
            EvaluationGroup{QString{}, {EvaluationLine{
                QObject::tr("Waiting for timer state"), {}, 0, false}}}
        );
        return result;
    }
    if (scenario.reset_pending.has_value()) {
        result.push_back(
            EvaluationGroup{QString{}, {EvaluationLine{
                QObject::tr("Waiting for Reset confirmation"), {}, 0, false}}}
        );
        return result;
    }

    std::vector<EvaluationLine> pending;
    if (scenario.pending_action.has_value()) {
        pending.push_back(EvaluationLine{
            QObject::tr("Pending: %1")
                .arg(QString::fromStdString(std::string{to_string(*scenario.pending_action)})),
            {},
            0,
            false,
        });
    }

    const auto& snapshot = *scenario.snapshot;
    if (snapshot.phase == TimerPhase::not_running) {
        append_group(scenario.start, QObject::tr("Start"), 0, result);
    } else if (snapshot.phase == TimerPhase::ended) {
        append_group(scenario.incomplete, QObject::tr("Incomplete"), 0, result);
    } else if (
        snapshot.phase == TimerPhase::running || snapshot.phase == TimerPhase::paused
    ) {
        append_group(scenario.reset, QObject::tr("Reset"), 0, result);
        if (snapshot.split_index >= 0 &&
            static_cast<std::size_t>(snapshot.split_index) < scenario.splits.size()) {
            const auto& split = scenario.splits[static_cast<std::size_t>(snapshot.split_index)];
            EvaluationGroup group;
            group.label = QObject::tr("Split %1").arg(split.index + 1);
            const auto name = segment_name(instance, split.index);
            if (!name.isEmpty()) {
                group.label += QStringLiteral(" - ") + name;
            }
            append_rules(split.rules, 1, group.lines);
            if (!group.lines.empty()) {
                result.push_back(std::move(group));
            }
        }
    }

    if (!pending.empty()) {
        if (result.empty()) {
            result.push_back(EvaluationGroup{QString{}, std::move(pending)});
        } else {
            result.front().lines.insert(
                result.front().lines.begin(), pending.begin(), pending.end()
            );
        }
    }
    return result;
}

CardData card_data(const InstanceDiagnosticsSnapshot& instance) {
    CardData data;
    data.index = instance.index;
    data.has_state = true;
    data.state = instance.state;
    data.status = state_text(instance.state);
    data.error = QString::fromStdString(instance.error);
    data.groups = evaluation_groups(instance);
    if (!data.error.isEmpty()) {
        EvaluationGroup error_group;
        error_group.lines.push_back(
            EvaluationLine{QObject::tr("Error: %1").arg(data.error), {}, 0, false}
        );
        data.groups.insert(data.groups.begin(), std::move(error_group));
    }
    if (instance.scenario.has_value()) {
        const bool measured = instance.scenario->evaluation_count > 0;
        data.average = latency_text(
            instance.scenario->average_evaluation_ms, measured
        );
        data.maximum = latency_text(instance.scenario->max_evaluation_ms, measured);
    } else {
        data.average = QStringLiteral("-");
        data.maximum = QStringLiteral("-");
    }
    return data;
}

QString signature_of(const CardData& data) {
    QString signature;
    for (const auto& group : data.groups) {
        signature += group.label;
        signature += QLatin1Char('|');
        for (const auto& line : group.lines) {
            signature += QString::number(line.depth);
            signature += QLatin1Char(':');
            signature += line.label;
            signature += QLatin1Char(line.strong ? '!' : '.');
            signature += QLatin1Char('\n');
        }
    }
    return signature;
}

QColor status_color(InstanceState state, const theme::SemanticColors& colors) {
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

}  // namespace

QString scenario_overview(const ScenarioDiagnosticsSnapshot& scenario) {
    InstanceDiagnosticsSnapshot instance;
    instance.scenario = scenario;
    const auto groups = evaluation_groups(instance);
    QStringList lines;
    for (const auto& group : groups) {
        if (!group.label.isEmpty()) {
            lines.append(group.label);
        }
        for (const auto& line : group.lines) {
            lines.append(
                QString(line.depth * 2, QLatin1Char(' ')) + line.label +
                (line.detail.isEmpty() ? QString{} : QStringLiteral(" | ") + line.detail)
            );
        }
    }
    return lines.isEmpty() ? QObject::tr("No condition configured") : lines.join('\n');
}

class ScenarioCard final : public QFrame {
public:
    explicit ScenarioCard(QWidget* parent = nullptr) : QFrame(parent) {
        setObjectName(QStringLiteral("scenarioCard"));
        auto* layout = new QVBoxLayout(this);
        layout->setContentsMargins(14, 12, 14, 12);
        layout->setSpacing(8);

        auto* top = new QHBoxLayout;
        title_ = new QLabel(this);
        title_->setObjectName(QStringLiteral("cardTitle"));
        status_ = new QLabel(this);
        top->addWidget(title_);
        top->addStretch(1);
        top->addWidget(status_);
        layout->addLayout(top);

        auto* evaluating = new QLabel(tr("Evaluating"), this);
        evaluating->setProperty("role", QStringLiteral("muted"));
        layout->addWidget(evaluating);

        evaluation_body_ = new QWidget(this);
        evaluation_layout_ = new QVBoxLayout(evaluation_body_);
        evaluation_layout_->setContentsMargins(0, 0, 0, 0);
        evaluation_layout_->setSpacing(2);
        layout->addWidget(evaluation_body_);

        auto* divider = new QFrame(this);
        divider->setObjectName(QStringLiteral("dividerHorizontal"));
        divider->setFrameShape(QFrame::HLine);
        divider->setFixedHeight(1);
        layout->addWidget(divider);

        auto* footer = new QHBoxLayout;
        footer->setSpacing(12);
        auto* evaluation = new QLabel(tr("Evaluation"), this);
        evaluation->setProperty("role", QStringLiteral("muted"));
        evaluation->setMinimumWidth(90);
        auto* average_label = new QLabel(tr("Avg"), this);
        average_label->setProperty("role", QStringLiteral("muted"));
        average_ = new QLabel(QStringLiteral("-"), this);
        auto* max_label = new QLabel(tr("Max"), this);
        max_label->setProperty("role", QStringLiteral("muted"));
        maximum_ = new QLabel(QStringLiteral("-"), this);
        footer->addWidget(evaluation);
        footer->addWidget(average_label);
        footer->addWidget(average_);
        footer->addSpacing(8);
        footer->addWidget(max_label);
        footer->addWidget(maximum_);
        footer->addStretch(1);
        layout->addLayout(footer);
    }

    void apply(const CardData& card) {
        const QString title = tr("Scenario %1").arg(card.index);
        if (title_->text() != title) {
            title_->setText(title);
        }
        const auto colors = theme::colors(theme::current_mode());
        const QString status_text =
            QString(QChar(0x25CF)) + QStringLiteral(" ") + card.status;
        const QString color = (card.has_state ? status_color(card.state, colors)
                                              : colors.muted)
                                  .name();
        if (status_->text() != status_text || status_color_ != color) {
            status_->setText(status_text);
            status_->setStyleSheet(
                QStringLiteral("color: %1; font-weight: 600;").arg(color)
            );
            status_color_ = color;
        }
        status_->setToolTip(card.error);

        const QString signature = signature_of(card);
        if (signature != signature_) {
            rebuild(card);
            signature_ = signature;
        }
        std::size_t row = 0;
        for (const auto& group : card.groups) {
            for (const auto& line : group.lines) {
                if (row >= rows_.size()) {
                    break;
                }
                if (rows_[row].first->text() != line.label) {
                    rows_[row].first->setText(line.label);
                }
                if (rows_[row].second->text() != line.detail) {
                    rows_[row].second->setText(line.detail);
                }
                ++row;
            }
        }
        if (average_->text() != card.average) {
            average_->setText(card.average);
        }
        if (maximum_->text() != card.maximum) {
            maximum_->setText(card.maximum);
        }
    }

private:
    void rebuild(const CardData& card) {
        while (QLayoutItem* item = evaluation_layout_->takeAt(0)) {
            delete item->widget();
            delete item;
        }
        rows_.clear();
        if (card.groups.empty()) {
            auto* empty = new QLabel(QStringLiteral("-"), evaluation_body_);
            empty->setProperty("role", QStringLiteral("muted"));
            evaluation_layout_->addWidget(empty);
            return;
        }
        for (const auto& group : card.groups) {
            if (!group.label.isEmpty()) {
                auto* header = new QLabel(group.label, evaluation_body_);
                QFont font = header->font();
                font.setBold(true);
                header->setFont(font);
                auto* container = new QWidget(evaluation_body_);
                auto* layout = new QHBoxLayout(container);
                layout->setContentsMargins(0, 4, 0, 0);
                layout->addWidget(header);
                layout->addStretch(1);
                evaluation_layout_->addWidget(container);
            }
            for (const auto& line : group.lines) {
                auto* row = new QWidget(evaluation_body_);
                auto* layout = new QHBoxLayout(row);
                layout->setContentsMargins(line.depth * kIndent, 0, 0, 0);
                layout->setSpacing(8);
                auto* label = new QLabel(line.label, row);
                if (line.strong) {
                    QFont font = label->font();
                    font.setBold(true);
                    label->setFont(font);
                }
                auto* detail = new QLabel(line.detail, row);
                detail->setProperty("role", QStringLiteral("muted"));
                theme::repolish(detail);
                detail->setTextInteractionFlags(Qt::TextSelectableByMouse);
                layout->addWidget(label);
                layout->addWidget(detail, 1);
                evaluation_layout_->addWidget(row);
                rows_.emplace_back(label, detail);
            }
        }
    }

    QLabel* title_;
    QLabel* status_;
    QWidget* evaluation_body_;
    QVBoxLayout* evaluation_layout_;
    QLabel* average_;
    QLabel* maximum_;
    QString signature_;
    QString status_color_;
    std::vector<std::pair<QLabel*, QLabel*>> rows_;
};

MonitorPage::MonitorPage(AppController* controller, QWidget* parent)
    : QWidget(parent), controller_(controller) {
    setObjectName(QStringLiteral("page"));
    connect(
        controller_, &AppController::sessionStarting, this,
        [this] { evaluation_rates_.clear(); }
    );

    auto* layout = new QHBoxLayout(this);
    layout->setContentsMargins(16, 14, 16, 14);
    layout->setSpacing(16);

    auto* left = new QWidget(this);
    left->setMinimumWidth(340);
    left->setMaximumWidth(520);
    auto* left_layout = new QVBoxLayout(left);
    left_layout->setContentsMargins(0, 0, 0, 0);
    left_layout->setSpacing(10);
    layout->addWidget(left);

    auto* status_title = new QLabel(tr("Global Status"), left);
    status_title->setObjectName(QStringLiteral("sectionTitle"));
    left_layout->addWidget(status_title);
    state_value_ = add_status_row(left_layout, tr("State"), QStringLiteral("-"));
    input_fps_value_ = add_status_row(left_layout, tr("Input FPS"), tr("- fps"));
    processing_fps_value_ =
        add_status_row(left_layout, tr("Processing FPS"), tr("- fps"));

    auto* input_title = new QLabel(tr("Input Preview"), left);
    input_title->setObjectName(QStringLiteral("sectionTitle"));
    left_layout->addWidget(input_title);
    preview_ = new ImageView(left);
    preview_->setMinimumHeight(220);
    preview_->setMaximumHeight(360);
    left_layout->addWidget(preview_);
    input_detail_ = new QLabel(tr("Input: stopped"), left);
    input_detail_->setProperty("role", QStringLiteral("muted"));
    left_layout->addWidget(input_detail_);

    error_label_ = new QLabel(left);
    error_label_->setObjectName(QStringLiteral("errorBanner"));
    error_label_->setWordWrap(true);
    error_label_->hide();
    left_layout->addWidget(error_label_);
    left_layout->addStretch(1);

    auto* right = new QWidget(this);
    auto* right_layout = new QVBoxLayout(right);
    right_layout->setContentsMargins(0, 0, 0, 0);
    right_layout->setSpacing(8);
    layout->addWidget(right, 1);

    auto* overview_header = new QHBoxLayout;
    auto* overview_title = new QLabel(tr("Scenario Overview"), right);
    overview_title->setObjectName(QStringLiteral("sectionTitle"));
    reset_button_ = new ResetAllButton(right);
    overview_header->addWidget(overview_title);
    overview_header->addStretch(1);
    overview_header->addWidget(reset_button_);
    right_layout->addLayout(overview_header);
    connect(reset_button_, &ResetAllButton::holdCompleted, this, &MonitorPage::resetRequested);

    scroll_ = new QScrollArea(right);
    scroll_->setWidgetResizable(true);
    scroll_->setFrameShape(QFrame::NoFrame);
    scroll_->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    cards_container_ = new QWidget(scroll_);
    cards_container_->setObjectName(QStringLiteral("page"));
    cards_layout_ = new QVBoxLayout(cards_container_);
    cards_layout_->setContentsMargins(0, 0, 8, 0);
    cards_layout_->setSpacing(10);
    cards_layout_->setAlignment(Qt::AlignTop);
    scroll_->setWidget(cards_container_);
    right_layout->addWidget(scroll_, 1);
}

QLabel* MonitorPage::add_status_row(
    QVBoxLayout* layout,
    const QString& label,
    const QString& initial
) {
    auto* row = new QWidget(this);
    auto* row_layout = new QHBoxLayout(row);
    row_layout->setContentsMargins(0, 0, 0, 0);
    row_layout->setSpacing(12);
    auto* name = new QLabel(label, row);
    name->setProperty("role", QStringLiteral("muted"));
    name->setMinimumWidth(110);
    auto* value = new QLabel(initial, row);
    value->setTextInteractionFlags(Qt::TextSelectableByMouse);
    row_layout->addWidget(name);
    row_layout->addWidget(value);
    row_layout->addStretch(1);
    layout->addWidget(row);
    return value;
}

void MonitorPage::refresh() {
    const auto preview = controller_->session().latest_preview();
    if (preview && !preview->empty()) {
        preview_->set_image(mat_to_qimage(*preview));
    } else {
        preview_->clear();
    }

    const auto capture = controller_->session().capture_stats();
    const auto colors = theme::colors(theme::current_mode());
    const bool running = controller_->session().running();
    state_value_->setText(running ? tr("Running") : tr("Stopped"));
    state_value_->setStyleSheet(
        QStringLiteral("color: %1; font-weight: 600;")
            .arg((running ? colors.active : colors.stopped).name())
    );
    input_fps_value_->setText(
        capture.frames_published > 0
            ? tr("%1 fps").arg(capture.measured_fps, 0, 'f', 1)
            : tr("- fps")
    );
    input_detail_->setText(
        tr("Input: %1 frames  |  %2")
            .arg(capture.frames_published)
            .arg(running ? tr("running") : tr("stopped"))
    );

    const auto instances = controller_->session().instance_diagnostics();
    if (instances.empty()) {
        evaluation_rates_.clear();
    }
    const auto now = std::chrono::steady_clock::now();
    double processing_fps = 0.0;
    for (const auto& instance : instances) {
        const auto count = instance.scenario ? instance.scenario->evaluation_count : 0;
        auto [rate_it, inserted] = evaluation_rates_.try_emplace(
            instance.index, EvaluationRate{instance.generation, count, now, 0.0}
        );
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
        processing_fps += rate.fps;
    }
    processing_fps_value_->setText(
        instances.empty() ? tr("- fps") : tr("%1 fps").arg(processing_fps, 0, 'f', 1)
    );

    const auto error = controller_->last_error();
    error_label_->setText(error);
    error_label_->setVisible(!error.isEmpty());

    std::vector<int> order;
    order.reserve(instances.size());
    for (const auto& instance : instances) {
        order.push_back(instance.index);
        auto found = cards_.find(instance.index);
        ScenarioCard* card = nullptr;
        if (found == cards_.end()) {
            card = new ScenarioCard(cards_container_);
            cards_[instance.index] = card;
            cards_layout_->addWidget(card);
        } else {
            card = found->second;
        }
        card->apply(card_data(instance));
    }
    for (auto it = cards_.begin(); it != cards_.end();) {
        if (std::find(order.begin(), order.end(), it->first) == order.end()) {
            it->second->deleteLater();
            it = cards_.erase(it);
        } else {
            ++it;
        }
    }
    if (order != card_order_) {
        for (const int index : order) {
            if (const auto found = cards_.find(index); found != cards_.end()) {
                cards_layout_->addWidget(found->second);
            }
        }
        card_order_ = order;
    }
}

}  // namespace divergencesplitter::ui
