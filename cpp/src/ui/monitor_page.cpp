#include "divergencesplitter/ui/monitor_page.hpp"

#include <QHeaderView>
#include <QLabel>
#include <QTableWidget>
#include <QVBoxLayout>

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

}  // namespace

MonitorPage::MonitorPage(AppController* controller, QWidget* parent)
    : QWidget(parent), controller_(controller) {
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
    instance_table_->setColumnCount(6);
    instance_table_->setHorizontalHeaderLabels(
        {tr("Scenario"), tr("State"), tr("Phase"), tr("Split"), tr("Last action"), tr("Detail")}
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
    }
    instance_table_->resizeColumnsToContents();

    const QString runtime_error = controller_->last_error();
    error_label_->setText(runtime_error);
    error_label_->setVisible(!runtime_error.isEmpty());
}

}  // namespace divergencesplitter::ui
