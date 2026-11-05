#pragma once

#include <QWidget>

#include <chrono>
#include <map>
#include <vector>

#include "divergencesplitter/runtime/diagnostics.hpp"

class QLabel;
class QScrollArea;
class QVBoxLayout;

namespace divergencesplitter::ui {

class AppController;
class ImageView;
class ResetAllButton;
class ScenarioCard;

[[nodiscard]] QString scenario_overview(const ScenarioDiagnosticsSnapshot& scenario);

class MonitorPage final : public QWidget {
    Q_OBJECT

public:
    explicit MonitorPage(AppController* controller, QWidget* parent = nullptr);

    void refresh();

signals:
    void resetRequested();

private:
    struct EvaluationRate {
        std::uint64_t generation{};
        std::uint64_t count{};
        std::chrono::steady_clock::time_point sampled_at;
        double fps{};
    };

    QLabel* add_status_row(
        QVBoxLayout* layout,
        const QString& label,
        const QString& initial
    );

    AppController* controller_;
    ImageView* preview_;
    QLabel* state_value_;
    QLabel* input_fps_value_;
    QLabel* processing_fps_value_;
    QLabel* input_detail_;
    QLabel* error_label_;
    QScrollArea* scroll_;
    QWidget* cards_container_;
    QVBoxLayout* cards_layout_;
    ResetAllButton* reset_button_;
    std::map<int, ScenarioCard*> cards_;
    std::vector<int> card_order_;
    std::map<int, EvaluationRate> evaluation_rates_;
};

}  // namespace divergencesplitter::ui
