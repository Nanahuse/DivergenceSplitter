#pragma once

#include <map>
#include <memory>
#include <string>
#include <vector>
#include <set>

#include "divergencesplitter/runtime/diagnostics.hpp"
#include "monitor_model.hpp"
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
    const std::set<std::string>& hold_paths = {}, const HistoryPaths* paths = nullptr);

enum class SharedMarkerKind { reset, error, transition, timer_reset };

struct SharedHistoryPoint {
    MonotonicTime time;
    float value{};
    bool operator==(const SharedHistoryPoint&) const = default;
};

struct SharedHistorySeries {
    std::string path;
    bool current{};
    double last_observation{};
    std::vector<std::vector<SharedHistoryPoint>> segments;
    std::vector<SharedHistoryPoint> states;
};

struct SharedHistoryMarker {
    MonotonicTime time;
    SharedMarkerKind kind{};
    bool operator==(const SharedHistoryMarker&) const = default;
};

struct SharedTraceMesh;

struct SharedHistoryChart {
    double seconds{};
    std::vector<SharedHistorySeries> series;
    std::vector<SharedHistoryMarker> markers;
    mutable std::shared_ptr<SharedTraceMesh> trace_mesh;
};

struct SharedPlotClick { bool clicked{}; std::string_view path; };

[[nodiscard]] SharedHistoryChart prepare_shared_chart(const std::vector<SharedHistorySource>& sources,
    MonotonicTime sampled_at, std::chrono::seconds window, const std::vector<MonotonicTime>& timer_resets,
    SharedHistoryChart previous = {});
[[nodiscard]] ImVec4 shared_series_color(std::string_view path, const theme::ChartColors& palette, bool current = true);
SharedPlotClick draw_shared_chart(const char* id, const SharedHistoryChart& chart, double now,
    double seconds, ImVec2 size, const theme::ChartColors& palette, float scale);

// Small plots return true when clicked. Detailed plots allow pan/zoom and pause live time.
bool draw_history_plot(const char* id, const ConditionDiagnosticsNode& condition,
    const HistoryPlots& history, double now, double seconds, float height,
    const theme::ChartColors& palette, bool detail = false, bool state = false,
    PlotViewport* viewport = nullptr);
bool draw_detector_comparison(const std::vector<const ConditionDiagnosticsNode*>& conditions,
    const HistoryPlots& history, double now, double seconds, float height,
    const theme::ChartColors& palette, PlotViewport* viewport = nullptr);

} // namespace divergencesplitter::ui
