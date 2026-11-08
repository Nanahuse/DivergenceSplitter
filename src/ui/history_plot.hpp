#pragma once

#include <map>
#include <string>
#include <vector>

#include "divergencesplitter/runtime/diagnostics.hpp"
#include "theme.hpp"

namespace divergencesplitter::ui {

struct PlotSegment { int begin{}; int count{}; };
struct HistoryPlotData {
    std::vector<double> times;
    std::vector<double> values;
    std::vector<double> states;
    std::vector<PlotSegment> segments;
    std::vector<PlotSegment> state_segments;
    std::vector<double> resets;
    std::vector<double> transitions;
    std::vector<double> errors;
};
using HistoryPlots = std::map<std::string, HistoryPlotData>;

[[nodiscard]] HistoryPlots prepare_history(const EvaluationHistorySnapshot& history);
void draw_history_plot(const char* id, const ConditionDiagnosticsNode& condition,
    const HistoryPlots& history, double now, double seconds, float height,
    const theme::Colors& palette, bool detail = false, bool state = false);
void draw_detector_comparison(const std::vector<const ConditionDiagnosticsNode*>& conditions,
    const HistoryPlots& history, double now, double seconds, float height,
    const theme::Colors& palette);

} // namespace divergencesplitter::ui
