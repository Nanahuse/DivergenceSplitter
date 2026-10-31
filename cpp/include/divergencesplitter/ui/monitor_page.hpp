#pragma once

#include <QWidget>
#include <chrono>
#include <map>
#include "divergencesplitter/runtime/diagnostics.hpp"

class QLabel;
class QTableWidget;

namespace divergencesplitter::ui {

class AppController;
class ImageView;
class ResetAllButton;

[[nodiscard]] QString scenario_overview(const ScenarioDiagnosticsSnapshot& scenario);

class MonitorPage final : public QWidget {
    Q_OBJECT

public:
    explicit MonitorPage(AppController* controller, QWidget* parent = nullptr);

    void refresh();

signals:
    void resetRequested();

private:
    AppController* controller_;
    ImageView* preview_;
    QLabel* capture_label_;
    QLabel* error_label_;
    QTableWidget* instance_table_;
    ResetAllButton* reset_button_;
    struct EvaluationRate {
        std::uint64_t generation{};
        std::uint64_t count{};
        std::chrono::steady_clock::time_point sampled_at;
        double fps{};
    };
    std::map<int, EvaluationRate> evaluation_rates_;
};

}  // namespace divergencesplitter::ui
