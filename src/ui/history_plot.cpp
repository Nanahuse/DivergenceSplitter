#include "history_plot.hpp"

#include <implot.h>

#include <algorithm>
#include <cmath>

namespace divergencesplitter::ui {
namespace {
struct GetterData {
    const HistoryPlotData* data;
    double now;
    int begin;
    bool state;
};
ImPlotPoint point(int index, void* pointer) {
    const auto& context = *static_cast<GetterData*>(pointer);
    const auto i = static_cast<std::size_t>(index + context.begin);
    return {context.data->times[i] - context.now,
            context.state ? context.data->states[i] : context.data->values[i]};
}
void series(const char* label, const HistoryPlotData& data, double now, bool stairs, bool state) {
    const auto& segments = state ? data.state_segments : data.segments;
    for (const auto& segment : segments) {
        GetterData getter{&data, now, segment.begin, state};
        if (stairs) ImPlot::PlotStairsG(label, point, &getter, segment.count);
        else ImPlot::PlotLineG(label, point, &getter, segment.count);
        // A single measurement (including zero) must remain visible.
        if (segment.count == 1) ImPlot::PlotScatterG(label, point, &getter, 1);
    }
}
void markers(const char* label, const std::vector<double>& times, double now, const ImVec4& color) {
    if (times.empty()) return;
    ImPlot::SetNextLineStyle(color, 1.0f);
    // Event coordinates are tiny and copied only for visible markers.
    for (const double time : times) {
        const double x = time - now;
        ImPlot::PlotInfLines(label, &x, 1);
    }
}
void plot_colors(const theme::Colors& palette) {
    ImPlot::PushStyleColor(ImPlotCol_PlotBg, palette.surface_low);
    ImPlot::PushStyleColor(ImPlotCol_AxisText, palette.text_secondary);
    ImPlot::PushStyleColor(ImPlotCol_AxisGrid, palette.divider);
}
}

HistoryPlots prepare_history(const EvaluationHistorySnapshot& history) {
    HistoryPlots result;
    for (const auto& condition : history.conditions) {
        auto& plot = result[condition.path];
        bool value_open = false, state_open = false;
        for (const auto& sample : condition.samples) {
            const double time = sample.time.nanoseconds / 1e9;
            if (sample.event == HistoryEvent::reset) plot.resets.push_back(time);
            if (sample.event == HistoryEvent::transition) plot.transitions.push_back(time);
            if (sample.event == HistoryEvent::error) plot.errors.push_back(time);
            const int index = static_cast<int>(plot.times.size());
            plot.times.push_back(time);
            plot.values.push_back(sample.value.value_or(0));
            plot.states.push_back(sample.result.value_or(false) ? 1 : 0);
            if (sample.value && std::isfinite(*sample.value)) {
                if (!value_open) plot.segments.push_back({index, 0});
                ++plot.segments.back().count;
                value_open = true;
            } else value_open = false;
            if (sample.result) {
                if (!state_open) plot.state_segments.push_back({index, 0});
                ++plot.state_segments.back().count;
                state_open = true;
            } else state_open = false;
        }
    }
    return result;
}

void draw_history_plot(const char* id, const ConditionDiagnosticsNode& condition,
    const HistoryPlots& history, double now, double seconds, float height,
    const theme::Colors& palette, bool detail, bool state) {
    if (!ImGui::IsRectVisible(ImVec2(ImGui::GetContentRegionAvail().x, height))) {
        ImGui::Dummy(ImVec2(0, height));
        return;
    }
    plot_colors(palette);
    const auto flags = detail ? ImPlotFlags_NoMenus : ImPlotFlags_CanvasOnly | ImPlotFlags_NoInputs;
    if (ImPlot::BeginPlot(id, ImVec2(-1, height), flags)) {
        const auto axis_flags = detail ? ImPlotAxisFlags_Lock : ImPlotAxisFlags_NoDecorations | ImPlotAxisFlags_Lock;
        ImPlot::SetupAxes(detail ? "Time (seconds ago)" : nullptr,
                          detail ? (state ? "result" : condition.measurement.unit.c_str()) : nullptr,
                          axis_flags, axis_flags);
        ImPlot::SetupAxisLimits(ImAxis_X1, -seconds, 0, ImPlotCond_Always);
        double minimum = state ? 0.0 : std::min(0.0, condition.measurement.target.value_or(0.0));
        double maximum = state ? 1.0 : std::max(0.0, condition.measurement.target.value_or(1.0));
        const auto found = history.find(condition.path);
        if (found != history.end() && !state)
            for (std::size_t i = 0; i < found->second.values.size(); ++i)
                if (found->second.times[i] >= now - seconds) {
                    minimum = std::min(minimum, found->second.values[i]);
                    maximum = std::max(maximum, found->second.values[i]);
                }
        if (condition.measurement.unit == "score") maximum = std::max(1.0, maximum);
        const double range = maximum > minimum ? maximum - minimum : 1.0;
        ImPlot::SetupAxisLimits(ImAxis_Y1, minimum - 0.05 * range,
                                maximum + 0.1 * range, ImPlotCond_Always);
        if (found != history.end()) {
            ImPlot::SetNextLineStyle(palette.primary, 2.0f);
            series(state ? "Result" : "Value", found->second, now, state || condition.measurement.stairs, state);
            markers("Reset", found->second.resets, now, palette.warning);
            markers("Transition", found->second.transitions, now, palette.active);
            markers("Error", found->second.errors, now, palette.error);
        }
        if (condition.measurement.target && !state) {
            const double target = *condition.measurement.target;
            ImPlot::SetNextLineStyle(palette.warning, 1.0f);
            ImPlot::PlotInfLines("Target", &target, 1, ImPlotInfLinesFlags_Horizontal);
        }
        ImPlot::EndPlot();
    }
    ImPlot::PopStyleColor(3);
}

void draw_detector_comparison(const std::vector<const ConditionDiagnosticsNode*>& conditions,
    const HistoryPlots& history, double now, double seconds, float height, const theme::Colors& palette) {
    plot_colors(palette);
    if (ImPlot::BeginPlot("##detector_comparison", ImVec2(-1, height), ImPlotFlags_NoMenus)) {
        ImPlot::SetupAxes("Time (seconds ago)", "score", ImPlotAxisFlags_Lock, ImPlotAxisFlags_AutoFit);
        ImPlot::SetupAxisLimits(ImAxis_X1, -seconds, 0, ImPlotCond_Always);
        for (const auto* condition : conditions) {
            const auto found = history.find(condition->path);
            if (found == history.end()) continue;
            const auto label = condition->path + " (" + condition->detector_type + ")";
            series(label.c_str(), found->second, now, false, false);
            if (condition->minimum_score) {
                const auto target_label = condition->path + " target";
                const double target = *condition->minimum_score;
                ImPlot::PlotInfLines(target_label.c_str(), &target, 1, ImPlotInfLinesFlags_Horizontal);
            }
        }
        ImPlot::EndPlot();
    }
    ImPlot::PopStyleColor(3);
}
} // namespace divergencesplitter::ui
