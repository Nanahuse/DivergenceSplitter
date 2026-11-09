// Run a Release build with DIVERGENCESPLITTER_BUILD_BENCHMARKS=ON.
// Measures the actual diagnostics mutex path, plot preparation and evaluator latency.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <iostream>
#include <cmath>
#include <implot.h>
#include <thread>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/runtime/scenario_runtime.hpp"
#include "history_plot.hpp"
#include "monitor_model.hpp"

using namespace divergencesplitter;
using namespace divergencesplitter::ui;
using namespace std::chrono_literals;
namespace {
struct Clock final : TimeProvider {
    std::atomic<std::int64_t> ns{};
    MonotonicTime now() const override { return {ns.load()}; }
};
ConditionPtr tree(int nodes) {
    std::vector<ConditionPtr> children;
    for (int i = 1; i < nodes; ++i) children.push_back(std::make_shared<ElapsedCondition>(120s));
    return std::make_shared<AllCondition>(std::move(children));
}
double ms(std::chrono::steady_clock::time_point from) {
    return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - from).count();
}
void stats(const char* name, std::vector<double> values) {
    std::sort(values.begin(), values.end());
    std::cout << name << "_p50_ms=" << values[values.size()/2]
              << " " << name << "_p95_ms=" << values[values.size()*95/100]
              << " " << name << "_max_ms=" << values.back() << ' ';
}
void run(int splits, int common_nodes, bool filtered, std::chrono::seconds window) {
    auto clock = std::make_shared<Clock>();
    Scenario scenario;
    scenario.start_condition = tree(10);
    scenario.reset_condition = tree(common_nodes);
    for (int i = 0; i < splits; ++i)
        scenario.splits.push_back(std::vector<ScenarioRulePtr>{std::make_shared<Rule>(tree(10), Action{ActionOperation::split})});
    ScenarioRuntime runtime{std::move(scenario), clock};
    LiveSplitUpdate update{UpdateKind::initial, {1, 1, 1, TimerPhase::running, 0, splits}, {}};
    runtime.apply_update(update);
    int active = 0;
    for (int i = 0; i < 3600; ++i) {
        clock->ns = static_cast<std::int64_t>(i) * 1'000'000'000 / 60;
        const int next = i * splits / 3600;
        if (next != active) {
            active = next;
            update.kind = UpdateKind::transition;
            ++update.snapshot.state_revision;
            update.snapshot.split_index = active;
            runtime.apply_update(update);
        }
        (void)runtime.evaluate(FrameContext{Frame{{}, clock->now()}, clock->now()});
    }
    std::size_t samples = 0;
    for (const auto& series : runtime.diagnostics(true).history->conditions) samples += series.samples.size();
    HistoryPaths selected{"reset.r0.cond", "reset.r0.cond.c0", "reset.r0.cond.c1"};
    const auto path = "split." + std::to_string(splits - 1) + ".r0.cond";
    selected.insert(path);
    selected.insert(path + ".c0");
    selected.insert(path + ".c1");
    const HistoryPaths* selection = filtered ? &selected : nullptr;
    std::vector<double> diagnostics, preparation, evaluation;
    std::atomic<bool> stop{};
    std::thread evaluator([&] {
        while (!stop) {
            const auto started = std::chrono::steady_clock::now();
            (void)runtime.evaluate(FrameContext{Frame{{}, clock->now()}, clock->now()});
            evaluation.push_back(ms(started));
            std::this_thread::sleep_until(started + 16ms);
        }
    });
    for (int i = 0; i < 20; ++i) {
        const auto started = std::chrono::steady_clock::now();
        auto snapshot = runtime.diagnostics(true, selection, window);
        diagnostics.push_back(ms(started));
        const auto prepare_started = std::chrono::steady_clock::now();
        InstanceDiagnosticsSnapshot instance;
        instance.scenario = std::move(snapshot);
        const auto model = card_model(instance);
        if (window > 0s) {
            const auto sources = shared_history_groups(model, window);
            const auto normal = prepare_shared_chart(sources.normal, model.history->sampled_at, window, model.history->timer_resets);
            const auto reset = prepare_shared_chart(sources.reset, model.history->sampled_at, window, model.history->timer_resets);
            if (normal.series.empty() || reset.series.empty()) std::terminate();
        } else if (prepare_history(*model.history).empty()) {
            std::terminate();
        }
        preparation.push_back(ms(prepare_started));
        std::this_thread::sleep_until(started + 100ms);
    }
    stop = true;
    evaluator.join();
    std::cout << "filtered=" << filtered << " window=" << window.count() << " splits=" << splits << " nodes_per_split=10 common_nodes=" << common_nodes
              << " samples=" << samples << ' ';
    stats("snapshot", diagnostics);
    stats("prepare", preparation);
    stats("evaluation_with_polling", evaluation);
    std::cout << '\n';
}
void render_benchmark() {
    auto* gui = ImGui::CreateContext();
    auto* plot = ImPlot::CreateContext();
    auto& io = ImGui::GetIO();
    io.IniFilename = nullptr;
    io.DisplaySize = ImVec2(1600, 3500);
    io.DeltaTime = 1.0f / 60;
    io.BackendFlags |= ImGuiBackendFlags_RendererHasVtxOffset;
    unsigned char* pixels; int width, height;
    io.Fonts->GetTexDataAsRGBA32(&pixels, &width, &height);
    const auto palette = theme::colors(theme::Mode::dark);
    for (const int count : {20, 100, 1000}) {
        std::vector<ConditionDiagnosticsNode> nodes(count);
        std::vector<ConditionHistory> histories(count);
        std::vector<SharedHistorySource> sources;
        for (int n = 0; n < count; ++n) {
            auto& node = nodes[n];
            node.path = "score." + std::to_string(n);
            node.type = "detected";
            node.measurement.target = 0.7;
            auto& history = histories[n];
            history.path = node.path;
            history.last_observation = MonotonicTime{60'000'000'000};
            for (int i = 0; i < 3600; ++i) {
                const auto event = i % 300 == 150 ? HistoryEvent::gap : i % 300 == 200 ? HistoryEvent::reset :
                    i % 300 == 250 ? HistoryEvent::error : HistoryEvent::sample;
                history.samples.push_back({{static_cast<std::int64_t>(i) * 1'000'000'000 / 60},
                    event == HistoryEvent::sample ? std::optional<double>{0.5 + 0.45 * std::sin(i * 0.03 + n)} : std::nullopt,
                    ConditionStatus::false_value, event, {}});
            }
            sources.push_back({&node, &history, n % 2 == 0});
        }
        std::vector<double> preparation, refresh, scroll;
        SharedHistoryChart chart;
        int vertices = 0;
        for (int frame = 0; frame < 66; ++frame) {
            auto started = std::chrono::steady_clock::now();
            const bool refresh_frame = frame % 6 == 0;
            const MonotonicTime now{60'000'000'000 + static_cast<std::int64_t>(frame) * 1'000'000'000 / 60};
            if (refresh_frame) {
                chart = prepare_shared_chart(sources, now, 60s, {}, std::move(chart));
                if (frame >= 6) preparation.push_back(ms(started));
            }
            started = std::chrono::steady_clock::now();
            ImGui::NewFrame();
            ImGui::SetNextWindowPos(ImVec2(0, 0));
            ImGui::SetNextWindowSize(ImVec2(500, 160));
            ImGui::Begin("Shared plot benchmark", nullptr, ImGuiWindowFlags_NoTitleBar);
            draw_shared_chart("shared", chart, now.nanoseconds / 1e9, 60, {460, 112}, palette, 1);
            ImGui::End();
            ImGui::Render();
            if (frame >= 6) (refresh_frame ? refresh : scroll).push_back(ms(started));
            vertices = ImGui::GetDrawData()->TotalVtxCount;
        }
        std::cout << "shared_series=" << count << " source_samples_per_series=3600 vertices=" << vertices << ' ';
        stats("prepare", preparation);
        stats("refresh_draw_cpu", refresh);
        stats("scroll_draw_cpu", scroll);
        std::cout << std::endl;
    }
    ImPlot::DestroyContext(plot);
    ImGui::DestroyContext(gui);
}
}
int main(int argc, char** argv) {
    if (argc > 1 && std::string_view{argv[1]} == "render") { render_benchmark(); return 0; }
    const bool recent = argc > 1 && std::string_view{argv[1]} == "shared";
    const auto window = recent ? 60s : 0s;
    const bool filtered = argc > 1;
    run(20, 10, filtered, window);
    run(100, 10, filtered, window);
    run(100, 1000, filtered, window);
}
