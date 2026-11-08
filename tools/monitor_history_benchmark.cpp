// Run a Release build with DIVERGENCESPLITTER_BUILD_BENCHMARKS=ON.
// Measures the actual diagnostics mutex path, plot preparation and evaluator latency.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <iostream>
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
void run(int splits, int common_nodes, bool filtered) {
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
        auto snapshot = runtime.diagnostics(true, selection);
        diagnostics.push_back(ms(started));
        const auto prepare_started = std::chrono::steady_clock::now();
        InstanceDiagnosticsSnapshot instance;
        instance.scenario = std::move(snapshot);
        const auto model = card_model(instance);
        const auto plots = prepare_history(*model.history);
        preparation.push_back(ms(prepare_started));
        if (plots.empty()) std::terminate();
        std::this_thread::sleep_until(started + 100ms);
    }
    stop = true;
    evaluator.join();
    std::cout << "filtered=" << filtered << " splits=" << splits << " nodes_per_split=10 common_nodes=" << common_nodes
              << " samples=" << samples << ' ';
    stats("snapshot", diagnostics);
    stats("prepare", preparation);
    stats("evaluation_with_polling", evaluation);
    std::cout << '\n';
}
}
int main(int argc, char**) {
    const bool filtered = argc > 1;
    run(20, 10, filtered);
    run(100, 10, filtered);
    run(100, 1000, filtered);
}
