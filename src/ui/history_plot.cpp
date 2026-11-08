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
void view_controls(const char* id, PlotViewport& view, double now, double seconds) {
    if (view.seconds != static_cast<int>(seconds)) {
        view.seconds = static_cast<int>(seconds);
        view.reset = true;
    }
    ImGui::PushID(id);
    if (ImGui::Button(view.follow ? "Pause live" : "Resume live")) {
        view.follow = !view.follow;
        view.anchor = now;
        if (view.follow) view.reset = true;
    }
    ImGui::SameLine();
    if (ImGui::Button("Reset view")) view.reset = true;
    ImGui::SameLine();
    ImGui::TextDisabled("Wheel: zoom | Drag: pan | Right-drag: select");
    ImGui::PopID();
    if (view.reset) {
        ++view.revision;
        view.x_min = -seconds;
        view.x_max = 0;
        view.follow = true;
        view.anchor = now;
    }
}
bool finish_interaction(PlotViewport* view, double origin) {
    const auto pos = ImPlot::GetPlotPos(), size = ImPlot::GetPlotSize();
    // NoInputs intentionally skips ImPlot's own hover/input update on small plots.
    const bool hovered = view ? (ImPlot::IsPlotHovered() || ImPlot::IsAxisHovered(ImAxis_X1) ||
                                  ImPlot::IsAxisHovered(ImAxis_Y1))
        : ImGui::IsWindowHovered() && ImGui::IsMouseHoveringRect(pos, ImVec2(pos.x + size.x, pos.y + size.y));
    if (!view) {
        if (hovered) ImGui::SetTooltip("Click to inspect and zoom");
        return hovered && ImGui::IsMouseClicked(ImGuiMouseButton_Left);
    }
    view->reset = false;
    if (hovered && (ImGui::GetIO().MouseWheel != 0 || ImGui::IsMouseDown(ImGuiMouseButton_Left) ||
                    ImGui::IsMouseDown(ImGuiMouseButton_Right) || ImGui::IsMouseDown(ImGuiMouseButton_Middle))) {
        view->follow = false;
        view->anchor = origin;
    }
    return false;
}
void plot_colors(const theme::Colors& palette) {
    ImPlot::PushStyleColor(ImPlotCol_PlotBg, palette.surface_low);
    ImPlot::PushStyleColor(ImPlotCol_AxisText, palette.text_secondary);
    ImPlot::PushStyleColor(ImPlotCol_AxisGrid, palette.divider);
}
}

HistoryPlots prepare_history(const EvaluationHistorySnapshot& history, const std::set<std::string>& hold_paths) {
    HistoryPlots result;
    for (const auto& condition : history.conditions) {
        auto& plot = result[condition.path];
        const bool hold = hold_paths.contains(condition.path);
        const auto capacity = condition.samples.size() * (hold ? 2 : 1);
        plot.times.reserve(capacity);
        plot.values.reserve(capacity);
        plot.states.reserve(capacity);
        bool value_open = false, state_open = false;
        for (const auto& sample : condition.samples) {
            const double time = sample.time.nanoseconds / 1e9;
            if (sample.event == HistoryEvent::reset) plot.resets.push_back(time);
            if (sample.event == HistoryEvent::transition) plot.transitions.push_back(time);
            if (sample.event == HistoryEvent::error) plot.errors.push_back(time);
            if (hold && value_open && sample.value == 0.0 &&
                !plot.values.empty() && plot.values.back() > 0.0) {
                // Hold failure occurs at this observation, not gradually over the prior interval.
                plot.times.push_back(time);
                plot.values.push_back(plot.values.back());
                plot.states.push_back(plot.states.back());
                ++plot.segments.back().count;
                if (state_open) ++plot.state_segments.back().count;
            }
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

bool draw_history_plot(const char* id, const ConditionDiagnosticsNode& condition,
    const HistoryPlots& history, double now, double seconds, float height,
    const theme::Colors& palette, bool detail, bool state, PlotViewport* viewport) {
    if (!ImGui::IsRectVisible(ImVec2(ImGui::GetContentRegionAvail().x, height))) {
        ImGui::Dummy(ImVec2(0, height));
        return false;
    }
    PlotViewport fallback;
    auto& view = viewport ? *viewport : fallback;
    if (detail) view_controls(id, view, now, seconds);
    const double origin = detail && !view.follow ? view.anchor : now;
    bool clicked = false;
    plot_colors(palette);
    if (detail) ImGui::PushID(static_cast<int>(view.revision));
    const auto flags = detail ? ImPlotFlags_NoMenus : ImPlotFlags_CanvasOnly | ImPlotFlags_NoInputs;
    if (ImPlot::BeginPlot(id, ImVec2(-1, height), flags)) {
        const auto axis_flags = detail ? ImPlotAxisFlags_None : ImPlotAxisFlags_NoDecorations | ImPlotAxisFlags_Lock;
        ImPlot::SetupAxes(detail ? (view.follow ? "Time (seconds ago)" : "Time (s from paused view)") : nullptr,
                          detail ? (state ? "result" : condition.measurement.unit.c_str()) : nullptr,
                          axis_flags, axis_flags);
        if (detail) ImPlot::SetupAxisLinks(ImAxis_X1, &view.x_min, &view.x_max);
        else ImPlot::SetupAxisLimits(ImAxis_X1, -seconds, 0, ImPlotCond_Always);
        double minimum = state ? 0.0 : std::min(0.0, condition.measurement.target.value_or(0.0));
        double maximum = state ? 1.0 : std::max(0.0, condition.measurement.target.value_or(1.0));
        const auto found = history.find(condition.path);
        if (found != history.end() && !state)
            for (std::size_t i = 0; i < found->second.values.size(); ++i)
                if (found->second.times[i] >= origin - seconds) {
                    minimum = std::min(minimum, found->second.values[i]);
                    maximum = std::max(maximum, found->second.values[i]);
                }
        if (condition.measurement.unit == "score") maximum = std::max(1.0, maximum);
        const double range = maximum > minimum ? maximum - minimum : 1.0;
        ImPlot::SetupAxisLimits(ImAxis_Y1, minimum - 0.05 * range,
                                maximum + 0.1 * range, detail ? ImPlotCond_Once : ImPlotCond_Always);
        if (found != history.end()) {
            ImPlot::SetNextLineStyle(palette.primary, 2.0f);
            series(state ? "Result" : "Value", found->second, origin, state || condition.measurement.stairs, state);
            markers("Reset", found->second.resets, origin, palette.warning);
            markers("Transition", found->second.transitions, origin, palette.active);
            markers("Error", found->second.errors, origin, palette.error);
        }
        if (condition.measurement.target && !state) {
            const double target = *condition.measurement.target;
            ImPlot::SetNextLineStyle(palette.warning, 1.0f);
            ImPlot::PlotInfLines("Target", &target, 1, ImPlotInfLinesFlags_Horizontal);
        }
        clicked = finish_interaction(detail ? &view : nullptr, origin);
        ImPlot::EndPlot();
    }
    ImPlot::PopStyleColor(3);
    if (detail) ImGui::PopID();
    return clicked;
}

bool draw_detector_comparison(const std::vector<const ConditionDiagnosticsNode*>& conditions,
    const HistoryPlots& history, double now, double seconds, float height, const theme::Colors& palette, PlotViewport* viewport) {
    if (!viewport && !ImGui::IsRectVisible(ImVec2(ImGui::GetContentRegionAvail().x, height))) {
        ImGui::Dummy(ImVec2(0, height));
        return false;
    }
    if (viewport) view_controls("comparison", *viewport, now, seconds);
    const double origin = viewport && !viewport->follow ? viewport->anchor : now;
    bool clicked = false;
    if (viewport) ImGui::PushID(static_cast<int>(viewport->revision));
    plot_colors(palette);
    if (ImPlot::BeginPlot("##detector_comparison", ImVec2(-1, height), viewport ? ImPlotFlags_NoMenus : ImPlotFlags_NoInputs | ImPlotFlags_NoMenus)) {
        ImPlot::SetupAxes(viewport && !viewport->follow ? "Time (s from paused view)" : "Time (seconds ago)", "score", viewport ? ImPlotAxisFlags_None : ImPlotAxisFlags_Lock, viewport ? ImPlotAxisFlags_None : ImPlotAxisFlags_Lock);
        if (viewport) ImPlot::SetupAxisLinks(ImAxis_X1, &viewport->x_min, &viewport->x_max);
        else ImPlot::SetupAxisLimits(ImAxis_X1, -seconds, 0, ImPlotCond_Always);
        double minimum = 0, maximum = 1;
        for (const auto* condition : conditions) {
            minimum = std::min(minimum, condition->minimum_score.value_or(0));
            maximum = std::max(maximum, condition->minimum_score.value_or(1));
        }
        ImPlot::SetupAxisLimits(ImAxis_Y1, minimum - 0.05, maximum + 0.1, viewport ? ImPlotCond_Once : ImPlotCond_Always);
        for (const auto* condition : conditions) {
            const auto found = history.find(condition->path);
            if (found == history.end()) continue;
            const auto label = condition->path + " (" + condition->detector_type + ")";
            series(label.c_str(), found->second, origin, false, false);
            if (condition->minimum_score) {
                const auto target_label = condition->path + " target";
                const double target = *condition->minimum_score;
                ImPlot::PlotInfLines(target_label.c_str(), &target, 1, ImPlotInfLinesFlags_Horizontal);
            }
        }
        clicked = finish_interaction(viewport, origin);
        ImPlot::EndPlot();
    }
    ImPlot::PopStyleColor(3);
    if (viewport) ImGui::PopID();
    return clicked;
}
} // namespace divergencesplitter::ui
