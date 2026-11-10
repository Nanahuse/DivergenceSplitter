#include "history_plot.hpp"

#include <implot.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>

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
void series(const char* label, const HistoryPlotData& data, double now, bool stairs, bool state,
    const ImVec4& color) {
    const auto& segments = state ? data.state_segments : data.segments;
    for (const auto& segment : segments) {
        GetterData getter{&data, now, segment.begin, state};
        ImPlot::SetNextLineStyle(color, 2.0f);
        if (stairs) ImPlot::PlotStairsG(label, point, &getter, segment.count);
        else ImPlot::PlotLineG(label, point, &getter, segment.count);
        // A single measurement (including zero) must remain visible.
        if (segment.count == 1) {
            ImPlot::SetNextMarkerStyle(ImPlotMarker_Circle, IMPLOT_AUTO, color, IMPLOT_AUTO, color);
            ImPlot::PlotScatterG(label, point, &getter, 1);
        }
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

}

HistoryPlots prepare_history(const EvaluationHistorySnapshot& history, const std::set<std::string>& hold_paths,
    const HistoryPaths* paths) {
    HistoryPlots result;
    for (const auto& condition : history.conditions) {
        if (paths && !paths->contains(condition.path)) continue;
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

namespace {
constexpr float progress_limit = 1.25f;

struct EnvelopePoint { SharedHistoryPoint point; std::size_t index{}; };

// Each bucket retains endpoints and extrema in sample order. A gap flushes
// the bucket and ends the polyline even when both sides land in one bucket.
class ProgressEnvelope {
public:
    ProgressEnvelope(SharedHistorySeries& series, bool stairs)
        : series_(series), stairs_(stairs) {}

    void add(SharedHistoryPoint point) {
        const auto bucket = history_preview_bucket(point.time);
        if (bucket != bucket_) flush();
        const EnvelopePoint sample{point, next_index_++};
        if (!has_bucket_) {
            extrema_.fill(sample);
            bucket_ = bucket;
            has_bucket_ = true;
        }
        extrema_[3] = sample;
        if (point.value < extrema_[1].point.value) extrema_[1] = sample;
        if (point.value >= extrema_[2].point.value) extrema_[2] = sample;
    }

    void finish_segment() {
        flush();
        segment_open_ = false;
    }

private:
    void flush() {
        if (!has_bucket_) return;
        if (!segment_open_) series_.segments.emplace_back();
        segment_open_ = true;
        auto& points = series_.segments.back();
        const auto emit = [&](const EnvelopePoint& sample) {
            const auto point = sample.point;
            if (!points.empty() && stairs_ && points.back().value != point.value)
                points.push_back({point.time, points.back().value});
            points.push_back(point);
        };
        const auto& first = extrema_.front();
        const auto& last = extrema_.back();
        const auto [earlier, later] = std::minmax(extrema_[1], extrema_[2],
            [](const auto& a, const auto& b) { return a.index < b.index; });
        emit(first);
        if (earlier.index > first.index && earlier.index < last.index) emit(earlier);
        if (later.index != earlier.index && later.index > first.index && later.index < last.index) emit(later);
        if (last.index != first.index) emit(last);
        has_bucket_ = false;
    }

    SharedHistorySeries& series_;
    bool stairs_;
    bool segment_open_{};
    bool has_bucket_{};
    std::int64_t bucket_{};
    std::size_t next_index_{};
    std::array<EnvelopePoint, 4> extrema_{};
};
}

struct SharedTraceMesh {
    ImVector<ImDrawVert> vertices;
    ImVector<ImDrawIdx> indices;
    ImVector<ImDrawCmd> commands;
    const ImDrawListSharedData* shared{};
    bool valid{};
    double anchor{};
    double pixels_per_second{};
    float height{};
    float right{};
    float bottom{};
    float scale{};
    float alpha{};
    float fringe{};
    std::array<float, 4> color_key{};
    std::vector<ImU32> inks;
    ImDrawListFlags flags{};
    ImTextureID texture{};
};

SharedHistoryChart prepare_shared_chart(const std::vector<SharedHistorySource>& sources,
    MonotonicTime sampled_at, std::chrono::seconds window, const std::vector<MonotonicTime>& timer_resets,
    SharedHistoryChart previous) {
    SharedHistoryChart result;
    if (previous.trace_mesh && previous.trace_mesh.use_count() == 1) {
        result.trace_mesh = std::move(previous.trace_mesh);
        result.trace_mesh->valid = false;
    }
    result.seconds = static_cast<double>(window.count());
    if (window <= std::chrono::seconds::zero()) return result;
    const auto cutoff = sampled_at - window;
    const auto preview_start = history_preview_start(cutoff);
    const auto first_bucket = history_preview_bucket(cutoff);
    using MarkerBucket = std::array<std::optional<MonotonicTime>, 4>;
    std::vector<MarkerBucket> markers(history_preview_bucket(sampled_at) - first_bucket + 1);
    const auto marker = [&](MonotonicTime time, SharedMarkerKind kind) {
        if (time < cutoff) return;
        auto& first = markers[history_preview_bucket(time) - first_bucket][static_cast<std::size_t>(kind)];
        if (!first || time < *first) first = time;
    };
    for (const auto time : timer_resets)
        if (time >= cutoff && time <= sampled_at) marker(time, SharedMarkerKind::timer_reset);

    result.series.reserve(sources.size());
    for (const auto& source : sources) {
        const auto& node = *source.condition;
        const auto& history = *source.history;
        const double target = node.measurement.target.value_or(0);
        const bool numeric = std::isfinite(target) && target > 0 && node.type != "once";
        auto& line = result.series.emplace_back();
        line.path = node.path;
        line.current = source.current;
        line.last_observation = history.last_observation.value_or(sampled_at).nanoseconds / 1e9;
        ProgressEnvelope envelope{line, node.measurement.stairs};
        std::optional<double> previous_value;
        std::optional<bool> previous_state;
        std::optional<SharedHistoryPoint> state_end;
        const auto finish_state = [&] {
            if (state_end) line.states.push_back(*state_end);
            state_end.reset();
            previous_state.reset();
        };
        const auto& samples = history.preview_samples ? *history.preview_samples : history.samples;
        for (const auto& sample : samples) {
            if (sample.time < preview_start || sample.time > sampled_at) {
                envelope.finish_segment();
                previous_value.reset();
                finish_state();
                continue;
            }
            if (sample.event == HistoryEvent::reset) marker(sample.time, SharedMarkerKind::reset);
            if (sample.event == HistoryEvent::error) marker(sample.time, SharedMarkerKind::error);
            if (sample.event == HistoryEvent::transition ||
                (previous_state && sample.result && *previous_state != *sample.result))
                marker(sample.time, SharedMarkerKind::transition);

            const bool boundary = sample.event == HistoryEvent::gap ||
                sample.event == HistoryEvent::reset || sample.event == HistoryEvent::error;
            if (numeric && !boundary && sample.value && std::isfinite(*sample.value)) {
                if (node.type == "hold" && *sample.value == 0 && previous_value.value_or(0) > 0)
                    envelope.add({sample.time, static_cast<float>(std::clamp(*previous_value / target, 0.0, double(progress_limit)))});
                envelope.add({sample.time, static_cast<float>(std::clamp(*sample.value / target, 0.0, double(progress_limit)))});
                previous_value = sample.value;
            } else {
                envelope.finish_segment();
                previous_value.reset();
            }

            if (boundary || !sample.result) {
                finish_state();
            } else if (!numeric) {
                const SharedHistoryPoint point{sample.time, *sample.result ? 1.0f : 0.0f};
                if (previous_state != sample.result) {
                    finish_state();
                    line.states.push_back(point);
                } else {
                    state_end = point;
                }
            }
            if (!boundary) previous_state = sample.result;
        }
        envelope.finish_segment();
        finish_state();
    }
    for (const auto& bucket : markers)
        for (std::size_t i = 0; i < bucket.size(); ++i)
            if (bucket[i]) result.markers.push_back({*bucket[i], static_cast<SharedMarkerKind>(i)});
    std::stable_partition(result.series.begin(), result.series.end(), [](const auto& line) { return !line.current; });
    return result;
}

namespace {
float luminance(const ImVec4& color) {
    const auto linear = [](float channel) {
        return channel <= 0.04045f ? channel / 12.92f : std::pow((channel + 0.055f) / 1.055f, 2.4f);
    };
    return 0.2126f * linear(color.x) + 0.7152f * linear(color.y) + 0.0722f * linear(color.z);
}

ImVec4 mix(const ImVec4& from, const ImVec4& to, float amount) {
    return {std::lerp(from.x, to.x, amount), std::lerp(from.y, to.y, amount),
            std::lerp(from.z, to.z, amount), 1.0f};
}

// Find the smallest adjustment that reaches the contrast target.
template<class MeetsTarget>
float contrast_adjustment(float initial, const MeetsTarget& meets) {
    if (meets(initial)) return initial;
    float low = initial, high = 1.0f;
    for (int i = 0; i < 8; ++i) {
        const float mid = (low + high) / 2;
        if (meets(mid)) high = mid;
        else low = mid;
    }
    return high;
}
}

ImVec4 shared_series_color(std::string_view path, const theme::ChartColors& palette, bool current) {
    std::uint32_t hash = 2166136261u;
    for (const unsigned char ch : path) hash = (hash ^ ch) * 16777619u;
    // Mix neighbouring paths before mapping to hue, so sibling indices spread out.
    hash ^= hash >> 16;
    hash *= 0x7feb352du;
    hash ^= hash >> 15;
    const float hue = static_cast<float>((hash & 0x00ffffffu) / 16777216.0);
    const float background = luminance(palette.background);
    const bool light = background > 0.5f;
    const float saturation = (light ? 0.72f : 0.56f) + 0.18f * ((hash >> 24) & 15u) / 15.0f;
    const float brightness = (light ? 0.51f : 0.83f) + 0.15f * (hash >> 28) / 15.0f;
    ImVec4 color{0, 0, 0, 1};
    ImGui::ColorConvertHSVtoRGB(hue, saturation, brightness, color.x, color.y, color.z);
    const auto contrast = [&](const ImVec4& ink) {
        const float ink_luminance = luminance(ink);
        return (std::max(background, ink_luminance) + 0.05f) / (std::min(background, ink_luminance) + 0.05f);
    };
    const ImVec4 endpoint = light ? ImVec4(0, 0, 0, 1) : ImVec4(1, 1, 1, 1);
    color = mix(color, endpoint, contrast_adjustment(0.0f, [&](float amount) {
        return contrast(mix(color, endpoint, amount)) >= 4.5f;
    }));
    if (!current) {
        color.w = contrast_adjustment(palette.history_alpha, [&](float alpha) {
            return contrast(mix(palette.background, color, alpha)) >= 3.2f;
        });
    }
    return color;
}

namespace {
void capture_trace_mesh(SharedTraceMesh& mesh, const ImDrawList& draw,
    int first_vertex, int first_index, int first_command) {
    const auto vertices = draw.VtxBuffer.Size - first_vertex;
    const auto indices = draw.IdxBuffer.Size - first_index;
    mesh.vertices.resize(vertices);
    mesh.indices.resize(indices);
    mesh.commands.resize(0);
    if (indices == 0) return;

    std::memcpy(mesh.vertices.Data, draw.VtxBuffer.Data + first_vertex, vertices * sizeof(ImDrawVert));
    std::memcpy(mesh.indices.Data, draw.IdxBuffer.Data + first_index, indices * sizeof(ImDrawIdx));
    for (int i = first_command; i < draw.CmdBuffer.Size; ++i) {
        const auto& source = draw.CmdBuffer[i];
        const auto start = std::max<unsigned int>(first_index, source.IdxOffset);
        const auto end = source.IdxOffset + source.ElemCount;
        if (start >= end) continue;
        ImDrawCmd command;
        command.IdxOffset = start - first_index;
        command.ElemCount = end - start;
        if (source.VtxOffset >= static_cast<unsigned int>(first_vertex)) {
            command.VtxOffset = source.VtxOffset - first_vertex;
        } else {
            // The first batch can share an existing window draw command.
            const auto prefix = first_vertex - source.VtxOffset;
            for (unsigned int j = command.IdxOffset; j < command.IdxOffset + command.ElemCount; ++j)
                mesh.indices[j] = static_cast<ImDrawIdx>(mesh.indices[j] - prefix);
        }
        mesh.commands.push_back(command);
    }
}

void append_trace_mesh(ImDrawList& draw, const SharedTraceMesh& mesh, float x, float y) {
    // The source commands share a texture and clip rect. Each splits the mesh
    // at an ImDrawIdx boundary, so PrimReserve can rebase it in the live list.
    for (int i = 0; i < mesh.commands.Size; ++i) {
        const auto& command = mesh.commands[i];
        if (command.ElemCount == 0) continue;
        const auto end = i + 1 < mesh.commands.Size ? mesh.commands[i + 1].VtxOffset : mesh.vertices.Size;
        const auto count = static_cast<int>(end - command.VtxOffset);
        draw.PrimReserve(command.ElemCount, count);
        const auto* source = mesh.vertices.Data + command.VtxOffset;
        for (int j = 0; j < count; ++j) {
            auto vertex = source[j];
            vertex.pos.x += x;
            vertex.pos.y += y;
            draw._VtxWritePtr[j] = vertex;
        }
        const auto* indices = mesh.indices.Data + command.IdxOffset;
        const auto base = draw._VtxCurrentIdx;
        if (base == 0) {
            std::memcpy(draw._IdxWritePtr, indices, command.ElemCount * sizeof(ImDrawIdx));
        } else {
            for (unsigned int j = 0; j < command.ElemCount; ++j)
                draw._IdxWritePtr[j] = static_cast<ImDrawIdx>(base + indices[j]);
        }
        draw._VtxWritePtr += count;
        draw._VtxCurrentIdx += count;
        draw._IdxWritePtr += command.ElemCount;
    }
}

void draw_shared_traces(ImDrawList& draw, const SharedHistoryChart& chart, double now,
    double seconds, double pixels_per_second, float right, float bottom, float height,
    const theme::ChartColors& palette, float scale) {
    const auto alpha = ImGui::GetStyle().Alpha;
    const std::array color_key{palette.background.x, palette.background.y, palette.background.z, palette.history_alpha};
    const auto texture = draw._CmdHeader.TextureId;
    const auto shared = ImGui::GetDrawListSharedData();
    auto& cached = chart.trace_mesh;
    if (!cached || !cached->valid || cached->shared != shared || now < cached->anchor ||
        cached->pixels_per_second != pixels_per_second || cached->height != height ||
        cached->scale != scale || cached->alpha != alpha || cached->color_key != color_key ||
        cached->flags != draw.Flags || cached->texture != texture || cached->fringe != draw._FringeScale) {
        if (!cached || cached.use_count() != 1 || cached->shared != shared)
            cached = std::make_shared<SharedTraceMesh>();
        auto& mesh = *cached;
        mesh.shared = shared;
        mesh.anchor = now;
        mesh.right = right;
        mesh.bottom = bottom;
        mesh.pixels_per_second = pixels_per_second;
        mesh.height = height;
        mesh.scale = scale;
        mesh.alpha = alpha;
        mesh.color_key = color_key;
        mesh.flags = draw.Flags;
        mesh.texture = texture;
        mesh.fringe = draw._FringeScale;
        const int first_vertex = draw.VtxBuffer.Size;
        const int first_index = draw.IdxBuffer.Size;
        const int first_command = draw.CmdBuffer.Size - 1;

        std::vector<ImVec2> points;
        mesh.inks.clear();
        mesh.inks.reserve(chart.series.size());
        for (const auto& line : chart.series) {
            const auto ink = ImGui::GetColorU32(shared_series_color(line.path, palette, line.current));
            mesh.inks.push_back(ink);
            if (line.last_observation < now - seconds || line.segments.empty()) continue;
            // Whole-pixel strokes use ImGui's baked antialiasing texture.
            const auto stroke = std::max(1.0f, std::round((line.current ? 1.6f : 1.0f) * scale));
            for (const auto& segment : line.segments) {
                if (segment.back().time.nanoseconds / 1e9 < now - seconds) continue;
                points.clear();
                for (const auto point : segment) {
                    const ImVec2 pixel{right + static_cast<float>((point.time.nanoseconds / 1e9 - now) * pixels_per_second),
                        bottom - point.value * height / progress_limit};
                    // Collapse horizontal edges only in the drawing mesh.
                    if (points.size() >= 2 && pixel.y == points.back().y && pixel.y == points[points.size() - 2].y &&
                        pixel.x >= points.back().x && points.back().x >= points[points.size() - 2].x)
                        points.back() = pixel;
                    else
                        points.push_back(pixel);
                }
                if (points.size() == 1) draw.AddCircleFilled(points.front(), 1.8f * scale, ink);
                else draw.AddPolyline(points.data(), static_cast<int>(points.size()), ink, ImDrawFlags_None, stroke);
            }
        }
        capture_trace_mesh(mesh, draw, first_vertex, first_index, first_command);
        mesh.valid = true;
        return;
    }
    const auto& mesh = *chart.trace_mesh;
    append_trace_mesh(draw, mesh, right - mesh.right + static_cast<float>((mesh.anchor - now) * pixels_per_second),
        bottom - mesh.bottom);
}
}

SharedPlotClick draw_shared_chart(const char* id, const SharedHistoryChart& chart, double now,
    double seconds, ImVec2 size, const theme::ChartColors& palette, float scale) {
    const auto origin = ImGui::GetCursorScreenPos();
    ImGui::InvisibleButton(id, size);
    SharedPlotClick result{ImGui::IsItemClicked(), {}};
    if (!ImGui::IsItemVisible()) return result;
    auto* draw = ImGui::GetWindowDrawList();
    const ImVec2 end{origin.x + size.x, origin.y + size.y};
    const float left = origin.x + 7 * scale, right = end.x - 7 * scale;
    const float top = origin.y + 6 * scale, bottom = end.y - (ImGui::GetFontSize() + 15 * scale);
    const float axis = end.y - ImGui::GetFontSize() - 2 * scale;
    const double pixels_per_second = (right - left) / seconds;
    const auto x_at = [&](MonotonicTime time) {
        return right + static_cast<float>((time.nanoseconds / 1e9 - now) * pixels_per_second);
    };
    const auto y_at = [&](float progress) { return bottom - progress * (bottom - top) / progress_limit; };
    draw->AddRectFilled(origin, end, ImGui::GetColorU32(palette.background), 4 * scale);
    draw->AddRect(origin, end, ImGui::GetColorU32(palette.border), 4 * scale);
    draw->PushClipRect(ImVec2(left, top), ImVec2(right, axis), true);
    const float goal = y_at(1);
    draw->AddLine(ImVec2(left, goal), ImVec2(right, goal), ImGui::GetColorU32(palette.target));
    draw->AddLine(ImVec2(left, bottom), ImVec2(right, bottom), ImGui::GetColorU32(palette.grid));

    const bool hovered = ImGui::IsItemHovered();
    const auto mouse = ImGui::GetIO().MousePos;
    float nearest = 144 * scale * scale;
    std::string_view hovered_path;
    const auto hit = [&](ImVec2 a, ImVec2 b, std::string_view path) {
        if (!hovered || std::max(a.x, b.x) < left || std::min(a.x, b.x) > right) return;
        const float dx = b.x - a.x, dy = b.y - a.y, length = dx * dx + dy * dy;
        const float t = length > 0 ? std::clamp(((mouse.x - a.x) * dx + (mouse.y - a.y) * dy) / length, 0.0f, 1.0f) : 0;
        const float x = mouse.x - a.x - t * dx, y = mouse.y - a.y - t * dy;
        const float distance = x * x + y * y;
        if (distance <= nearest) { nearest = distance; hovered_path = path; }
    };
    const bool matching_window = chart.seconds == seconds;
    if (matching_window)
        draw_shared_traces(*draw, chart, now, seconds, pixels_per_second, right, bottom, bottom - top, palette, scale);
    for (std::size_t i = 0; i < chart.series.size(); ++i) {
        const auto& line = chart.series[i];
        if (!matching_window || line.last_observation < now - seconds) continue;
        if (result.path.empty() || line.current) result.path = line.path;
        if (hovered) for (const auto& segment : line.segments) {
            if (x_at(segment.back().time) < std::max(left, mouse.x - 12 * scale) ||
                x_at(segment.front().time) > std::min(right, mouse.x + 12 * scale)) continue;
            ImVec2 previous{x_at(segment.front().time), y_at(segment.front().value)};
            for (const auto point : segment) {
                const ImVec2 pixel{x_at(point.time), y_at(point.value)};
                hit(previous, pixel, line.path);
                previous = pixel;
            }
        }
        if (line.states.empty()) continue;
        const auto ink = chart.trace_mesh->inks[i];
        for (const auto state : line.states) {
            const auto x = x_at(state.time);
            if (x < left || x > right) continue;
            const ImVec2 pixel{x, bottom + (state.value == 1 ? 3 : 8) * scale};
            hit(pixel, pixel, line.path);
            if (state.value == 1) draw->AddCircleFilled(pixel, 2 * scale, ink);
            else draw->AddLine(ImVec2(x - 2 * scale, pixel.y), ImVec2(x + 2 * scale, pixel.y), ink, scale);
        }
    }
    if (matching_window) for (const auto& marker : chart.markers) {
        const float x = x_at(marker.time);
        if (x < left || x > right) continue;
        const bool timer = marker.kind == SharedMarkerKind::timer_reset;
        auto color = marker.kind == SharedMarkerKind::error ? palette.error :
            marker.kind == SharedMarkerKind::transition ? palette.transition : palette.reset;
        draw->AddLine(ImVec2(x, top), ImVec2(x, bottom), ImGui::GetColorU32(color), (timer ? 2 : 1) * scale);
    }
    draw->PopClipRect();
    const auto label_color = ImGui::GetColorU32(palette.axis_text);
    const auto time_label = "-" + std::to_string(static_cast<int>(seconds)) + " s";
    draw->AddText(ImVec2(left, axis), label_color, time_label.c_str());
    draw->AddText(ImVec2(right - ImGui::CalcTextSize("now").x, axis), label_color, "now");
    draw->AddText(ImVec2(right - ImGui::CalcTextSize("100%").x, goal - ImGui::GetFontSize()),
                  label_color, "100%");
    if (result.path.empty() && (!matching_window || chart.markers.empty())) {
        const float message_y = (goal + bottom - ImGui::GetFontSize()) * 0.5f;
        draw->AddText(ImVec2(left + 8 * scale, message_y), label_color, "No recent history");
    }
    if (hovered) {
        if (!hovered_path.empty()) {
            result.path = hovered_path;
            ImGui::SetTooltip("%.*s\nClick to inspect", static_cast<int>(hovered_path.size()), hovered_path.data());
        } else ImGui::SetTooltip("100%% = target. Dots/dashes below = true/false.\n"
                                 "Orange: reset | Red: error | Green: transition\nClick to inspect");
    }
    return result;
}

bool draw_history_plot(const char* id, const ConditionDiagnosticsNode& condition,
    const HistoryPlots& history, double now, double seconds, float height,
    const theme::ChartColors& palette, bool detail, bool state, PlotViewport* viewport) {
    if (!ImGui::IsRectVisible(ImVec2(ImGui::GetContentRegionAvail().x, height))) {
        ImGui::Dummy(ImVec2(0, height));
        return false;
    }
    PlotViewport fallback;
    auto& view = viewport ? *viewport : fallback;
    if (detail) view_controls(id, view, now, seconds);
    const double origin = detail && !view.follow ? view.anchor : now;
    bool clicked = false;
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
            series(state ? "Result" : "Value", found->second, origin, state || condition.measurement.stairs, state, palette.trace);
            markers("Reset", found->second.resets, origin, palette.reset);
            markers("Transition", found->second.transitions, origin, palette.transition);
            markers("Error", found->second.errors, origin, palette.error);
        }
        if (condition.measurement.target && !state) {
            const double target = *condition.measurement.target;
            ImPlot::SetNextLineStyle(palette.target, 1.0f);
            ImPlot::PlotInfLines("Target", &target, 1, ImPlotInfLinesFlags_Horizontal);
        }
        clicked = finish_interaction(detail ? &view : nullptr, origin);
        ImPlot::EndPlot();
    }
    if (detail) ImGui::PopID();
    return clicked;
}

bool draw_detector_comparison(const std::vector<const ConditionDiagnosticsNode*>& conditions,
    const HistoryPlots& history, double now, double seconds, float height, const theme::ChartColors& palette, PlotViewport* viewport) {
    if (!viewport && !ImGui::IsRectVisible(ImVec2(ImGui::GetContentRegionAvail().x, height))) {
        ImGui::Dummy(ImVec2(0, height));
        return false;
    }
    if (viewport) view_controls("comparison", *viewport, now, seconds);
    const double origin = viewport && !viewport->follow ? viewport->anchor : now;
    bool clicked = false;
    if (viewport) ImGui::PushID(static_cast<int>(viewport->revision));
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
            const auto color = shared_series_color(condition->path, palette);
            series(label.c_str(), found->second, origin, false, false, color);
            if (condition->minimum_score) {
                const auto target_label = condition->path + " target";
                const double target = *condition->minimum_score;
                ImPlot::SetNextLineStyle(color, 1.0f);
                ImPlot::PlotInfLines(target_label.c_str(), &target, 1, ImPlotInfLinesFlags_Horizontal);
            }
        }
        clicked = finish_interaction(viewport, origin);
        ImPlot::EndPlot();
    }
    if (viewport) ImGui::PopID();
    return clicked;
}
} // namespace divergencesplitter::ui
