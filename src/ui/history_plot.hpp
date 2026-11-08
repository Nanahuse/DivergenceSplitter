#pragma once

#include <map>
#include <string>
#include <vector>
#include <set>

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

struct PlotViewport {
    bool follow{true};
    bool reset{true};
    int seconds{};
    double anchor{};
    double x_min{};
    double x_max{};
    std::uint64_t revision{};
};

[[nodiscard]] HistoryPlots prepare_history(const EvaluationHistorySnapshot& history,
    const std::set<std::string>& hold_paths = {});
// Small plots return true when clicked. Detailed plots allow pan/zoom and pause live time.
bool draw_history_plot(const char* id, const ConditionDiagnosticsNode& condition,
    const HistoryPlots& history, double now, double seconds, float height,
    const theme::Colors& palette, bool detail = false, bool state = false,
    PlotViewport* viewport = nullptr);
bool draw_detector_comparison(const std::vector<const ConditionDiagnosticsNode*>& conditions,
    const HistoryPlots& history, double now, double seconds, float height,
    const theme::Colors& palette, PlotViewport* viewport = nullptr);

} // namespace divergencesplitter::ui
