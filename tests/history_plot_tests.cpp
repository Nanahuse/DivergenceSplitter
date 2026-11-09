#include <gtest/gtest.h>
#include <imgui.h>
#include <implot.h>

#include "history_plot.hpp"
#include "monitor_model.hpp"
#include "monitor_row.hpp"

using namespace divergencesplitter;
using namespace divergencesplitter::ui;

TEST(HistoryPlot, NeverJoinsMeasurementsAcrossGapsErrorsOrResets) {
    EvaluationHistorySnapshot history;
    history.conditions.push_back({"condition", {
        {{0}, 0.0, ConditionStatus::false_value, HistoryEvent::sample, false},
        {{100}, 0.7, ConditionStatus::true_value, HistoryEvent::sample, true},
        {{200}, {}, ConditionStatus::skipped, HistoryEvent::gap, {}},
        {{300}, 0.5, ConditionStatus::true_value, HistoryEvent::sample, true},
        {{400}, {}, ConditionStatus::not_evaluated, HistoryEvent::reset, {}},
        {{400}, 0.0, ConditionStatus::false_value, HistoryEvent::sample, false},
        {{500}, {}, ConditionStatus::error, HistoryEvent::error, {}},
        {{600}, 0.2, ConditionStatus::false_value, HistoryEvent::sample, false},
    }});
    const auto plots = prepare_history(history);
    const auto& plot = plots.at("condition");
    ASSERT_EQ(plot.segments.size(), 4);
    EXPECT_EQ(plot.segments[0].count, 2);
    EXPECT_EQ(plot.segments[1].begin, 3);
    EXPECT_EQ(plot.segments[2].begin, 5);
    EXPECT_EQ(plot.segments[3].begin, 7);
    EXPECT_EQ(plot.values[0], 0);
    EXPECT_EQ(plot.resets.size(), 1);
    EXPECT_EQ(plot.errors.size(), 1);
}

TEST(MonitorModel, GraphTreeRetainsSkippedThenChildrenAndInactiveSequenceRules) {
    InstanceDiagnosticsSnapshot instance;
    instance.scenario.emplace();
    instance.scenario->snapshot = LiveSplitSnapshot{1, 1, 1, TimerPhase::running, 0, 1};
    RuleDiagnosticsNode sequence;
    sequence.path = "split.0.r0";
    sequence.active_rule_index = 1;
    for (std::size_t i = 0; i < 2; ++i) {
        RuleDiagnosticsNode rule;
        rule.path = sequence.path + ".s" + std::to_string(i);
        rule.condition.type = "then";
        rule.condition.children.resize(2);
        rule.condition.children[0].type = "detected";
        rule.condition.children[0].status = "skipped";
        rule.condition.children[1].type = "elapsed";
        rule.condition.children[1].status = "false";
        sequence.sequence_rules.push_back(rule);
    }
    instance.scenario->splits.push_back({"split.0", 0, true, {sequence}});
    const auto model = card_model(instance);
    ASSERT_EQ(model.rule_groups.size(), 1);
    const auto& rules = model.rule_groups[0].rules[0].sequence_rules;
    ASSERT_EQ(rules.size(), 2);
    ASSERT_EQ(rules[0].condition.children.size(), 2);
    EXPECT_EQ(rules[0].condition.children[0].status, "skipped");
}

TEST(HistoryPlot, RendersNumericStateStairsAndComparisonWithPinnedImPlot) {
    auto* gui = ImGui::CreateContext();
    auto* plot_context = ImPlot::CreateContext();
    auto& io = ImGui::GetIO();
    io.IniFilename = nullptr;
    io.DisplaySize = ImVec2(1024, 1000);
    io.DeltaTime = 1.0f / 60;
    unsigned char* pixels;
    int width, height;
    io.Fonts->GetTexDataAsRGBA32(&pixels, &width, &height);
    EvaluationHistorySnapshot history;
    history.conditions.push_back({"condition", {
        {{1'000'000'000}, 0.0, ConditionStatus::false_value, HistoryEvent::sample, false},
        {{2'000'000'000}, 1.0, ConditionStatus::true_value, HistoryEvent::transition, true},
        {{3'000'000'000}, {}, ConditionStatus::not_evaluated, HistoryEvent::reset, {}},
        {{4'000'000'000}, 0.0, ConditionStatus::skipped, HistoryEvent::sample, {}},
    }});
    const auto plots = prepare_history(history);
    ConditionDiagnosticsNode node;
    node.path = "condition";
    node.type = "detected";
    node.measurement = {1.0, 0.5, "score", false};
    node.minimum_score = 0.5;
    for (const auto mode : {theme::Mode::light, theme::Mode::dark}) {
        ImGui::NewFrame();
        ImGui::SetNextWindowSize(ImVec2(1000, 980));
        ImGui::Begin("Monitor plots");
        const auto palette = theme::colors(mode);
        draw_history_plot("score", node, plots, 5, 15, 65, palette);
        node.measurement.stairs = true;
        draw_history_plot("count", node, plots, 5, 30, 180, palette, true);
        draw_history_plot("state", node, plots, 5, 60, 180, palette, true, true);
        draw_detector_comparison({&node}, plots, 5, 30, 180, palette);
        ImGui::End();
        ImGui::Render();
        ASSERT_NE(ImGui::GetDrawData(), nullptr);
        EXPECT_GT(ImGui::GetDrawData()->TotalVtxCount, 0);
    }
    ImPlot::DestroyContext(plot_context);
    ImGui::DestroyContext(gui);
}

TEST(MonitorModel, EvaluationRatesAreIndependentAndResetOnNewHistoryIdentity) {
    MonitorEvaluationRate first, second;
    first.update(1, 0, 0);
    second.update(2, 0, 0);
    first.update(1, 30, 0.5);
    second.update(2, 10, 0.5);
    EXPECT_DOUBLE_EQ(first.fps(), 60);
    EXPECT_DOUBLE_EQ(second.fps(), 20);
    first.update(3, 0, 0.6);
    EXPECT_DOUBLE_EQ(first.fps(), 0);
    EXPECT_DOUBLE_EQ(second.fps(), 20);
    second.update(2, 10, 1);
    EXPECT_DOUBLE_EQ(second.fps(), 0);
}

TEST(MonitorModel, PastSplitsRemainSelectableAcrossSplitEndAndResetTransitions) {
    InstanceDiagnosticsSnapshot instance;
    auto& scenario = instance.scenario.emplace();
    scenario.snapshot = LiveSplitSnapshot{1, 1, 1, TimerPhase::running, 0, 2};
    const auto make_rule = [](const std::string& path) {
        RuleDiagnosticsNode rule;
        rule.path = path + ".r0";
        rule.condition.path = rule.path + ".cond";
        rule.condition.type = "detected";
        return rule;
    };
    scenario.start.push_back({"start", {make_rule("start")}});
    scenario.reset.push_back({"reset", {make_rule("reset")}});
    scenario.incomplete.push_back({"incomplete", {make_rule("incomplete")}});
    scenario.splits.push_back({"split.0", 0, true, {make_rule("split.0")}});
    scenario.splits.push_back({"split.1", 1, true, {make_rule("split.1")}});
    const auto current = [](const auto& model, const std::string& path) {
        for (const auto& group : model.rule_groups) if (group.path == path) return group.current;
        return false;
    };
    auto model = card_model(instance);
    ASSERT_EQ(model.rule_groups.size(), 5);
    EXPECT_TRUE(current(model, "split.0"));
    EXPECT_TRUE(current(model, "reset"));
    EXPECT_FALSE(current(model, "split.1"));
    scenario.snapshot->split_index = 1;
    model = card_model(instance);
    EXPECT_NE(find_condition(model, "split.0.r0.cond"), nullptr);
    EXPECT_FALSE(current(model, "split.0"));
    EXPECT_TRUE(current(model, "split.1"));
    scenario.snapshot->phase = TimerPhase::ended;
    model = card_model(instance);
    EXPECT_NE(find_condition(model, "split.0.r0.cond"), nullptr);
    EXPECT_TRUE(current(model, "incomplete"));
    EXPECT_FALSE(current(model, "split.1"));
    scenario.snapshot->phase = TimerPhase::not_running;
    scenario.snapshot->split_index = -1;
    model = card_model(instance);
    EXPECT_NE(find_condition(model, "split.1.r0.cond"), nullptr);
    EXPECT_TRUE(current(model, "start"));
    EXPECT_FALSE(current(model, "reset"));
}

TEST(HistoryPlot, HoldDropsVerticallyAtTheObservedTimeWithoutBridgingGaps) {
    EvaluationHistorySnapshot history;
    history.conditions.push_back({"hold", {
        {{1'000'000'000}, 0.4, ConditionStatus::false_value, HistoryEvent::sample, false},
        {{2'000'000'000}, 0.0, ConditionStatus::false_value, HistoryEvent::transition, false},
        {{3'000'000'000}, {}, ConditionStatus::skipped, HistoryEvent::gap, {}},
        {{4'000'000'000}, 0.0, ConditionStatus::false_value, HistoryEvent::sample, false}
    }});
    const auto plots = prepare_history(history, {"hold"});
    const auto& plot = plots.at("hold");
    EXPECT_EQ(plot.times, (std::vector<double>{1, 2, 2, 3, 4}));
    EXPECT_EQ(plot.values[1], 0.4);
    EXPECT_EQ(plot.values[2], 0.0);
    ASSERT_EQ(plot.segments.size(), 2);
    EXPECT_EQ(plot.segments[0].count, 3);
    EXPECT_EQ(plot.segments[1].begin, 4);
    EXPECT_EQ(history.conditions[0].samples.size(), 4); // Display geometry only.
}

namespace {
struct PlotFixture {
    ImGuiContext* gui = ImGui::CreateContext();
    ImPlotContext* plot = ImPlot::CreateContext();
    HistoryPlots history;
    ConditionDiagnosticsNode node;
    PlotFixture() {
        auto& io = ImGui::GetIO();
        io.IniFilename = nullptr;
        io.DisplaySize = ImVec2(1000, 800);
        io.DeltaTime = 1.0f / 60;
        unsigned char* pixels; int width, height;
        io.Fonts->GetTexDataAsRGBA32(&pixels, &width, &height);
        node.path = "score";
        node.measurement = {0.5, 0.5, "score", false};
        node.minimum_score = 0.5;
    }
    ~PlotFixture() { ImPlot::DestroyContext(plot); ImGui::DestroyContext(gui); }
    void begin() {
        ImGui::NewFrame();
        ImGui::SetNextWindowPos(ImVec2(0, 0));
        ImGui::SetNextWindowSize(ImVec2(900, 700));
        ImGui::Begin("Interaction test", nullptr, ImGuiWindowFlags_NoTitleBar | ImGuiWindowFlags_NoMove);
    }
    void end() { ImGui::End(); ImGui::Render(); }
};
}

TEST(HistoryPlot, SmallConditionAndComparisonPlotsOpenOnClick) {
    for (bool comparison : {false, true}) {
        PlotFixture fixture;
        const auto draw = [&] {
            return comparison ? draw_detector_comparison({&fixture.node}, fixture.history, 60, 30, 240, theme::colors(theme::Mode::dark))
                : draw_history_plot("small", fixture.node, fixture.history, 60, 30, 240, theme::colors(theme::Mode::dark));
        };
        fixture.begin();
        EXPECT_FALSE(draw());
        const auto min = ImGui::GetItemRectMin(), max = ImGui::GetItemRectMax();
        fixture.end();
        auto& io = ImGui::GetIO();
        io.AddMousePosEvent((min.x + max.x)/2, (min.y + max.y)/2);
        fixture.begin(); (void)draw(); fixture.end();
        io.AddMouseButtonEvent(ImGuiMouseButton_Left, true);
        fixture.begin();
        EXPECT_TRUE(draw());
        fixture.end();
    }
}

TEST(HistoryPlot, DetailAndComparisonZoomFreezeTimeAndKeepTheViewportUntilReset) {
    for (bool comparison : {false, true}) {
        PlotFixture fixture;
        PlotViewport view;
        const auto draw = [&](double now, int seconds) {
            if (comparison) draw_detector_comparison({&fixture.node}, fixture.history, now, seconds, 240, theme::colors(theme::Mode::dark), &view);
            else draw_history_plot("detail", fixture.node, fixture.history, now, seconds, 240, theme::colors(theme::Mode::dark), true, false, &view);
        };
        fixture.begin(); draw(60, 30);
        const auto min = ImGui::GetItemRectMin(), max = ImGui::GetItemRectMax();
        fixture.end();
        EXPECT_NEAR(view.x_max - view.x_min, 30, 1e-6);
        auto& io = ImGui::GetIO();
        io.AddMousePosEvent((min.x + max.x)/2, (min.y + max.y)/2);
        fixture.begin(); draw(60, 30); fixture.end();
        io.AddMouseWheelEvent(0, 1);
        fixture.begin(); draw(61, 30); fixture.end();
        EXPECT_FALSE(view.follow);
        EXPECT_LT(view.x_max - view.x_min, 30);
        const double left = view.x_min, right = view.x_max, anchor = view.anchor;
        fixture.begin(); draw(100, 30); fixture.end();
        EXPECT_DOUBLE_EQ(view.x_min, left);
        EXPECT_DOUBLE_EQ(view.x_max, right);
        EXPECT_DOUBLE_EQ(view.anchor, anchor);
        fixture.begin(); draw(100, 15); fixture.end();
        EXPECT_TRUE(view.follow);
        EXPECT_NEAR(view.x_max - view.x_min, 15, 1e-6);
    }
}

TEST(MonitorModel, UnaryConditionsMergeIntoOneRowWithoutDiscardingTheChild) {
    for (const auto* type : {"hold", "nth", "once", "rising_edge", "falling_edge", "not"}) {
        ConditionDiagnosticsNode root;
        root.type = type;
        root.path = "root";
        root.description = "hidden numeric configuration 0.95";
        root.children.resize(1);
        root.children[0].type = "detected";
        root.children[0].path = "root.c0";
        root.children[0].detector_type = "mean_brightness";
        const auto row = compact_condition_row(root);
        EXPECT_EQ(row.anchor, &root);
        EXPECT_EQ(row.label.find("0.95"), std::string::npos);
        EXPECT_EQ(row.label.find("mean_brightness"), std::string::npos);
        EXPECT_NE(row.label.find("detected"), std::string::npos);
        EXPECT_TRUE(compact_condition_children(row).empty());
        EXPECT_EQ(root.children.size(), 1);
    }
}

TEST(MonitorModel, CurrentCardsExcludeHistoryWithoutRemovingInspectorRoots) {
    ScenarioCardModel card;
    for (int i = 0; i < 3; ++i) {
        RuleDiagnosticsNode rule;
        rule.condition.type = "detected";
        rule.condition.path = "split." + std::to_string(i) + ".r0.cond";
        card.rule_groups.push_back({"Split " + std::to_string(i + 1) + " - Segment name",
            {rule}, "split." + std::to_string(i), i == 1});
    }
    const auto current = current_monitor_groups(card);
    ASSERT_EQ(current.size(), 1);
    EXPECT_EQ(current[0].label, "Split 2");
    EXPECT_EQ(current[0].source, &card.rule_groups[1]);
    EXPECT_EQ(inspector_rule_roots(card).size(), 3);
    EXPECT_NE(find_condition(card, "split.0.r0.cond"), nullptr);
    card.rule_groups[1].current = false;
    EXPECT_TRUE(current_monitor_groups(card).empty());
}

TEST(MonitorModel, CardsUseAvailableWidthAndRespectDpiAndInstanceCount) {
    EXPECT_EQ(monitor_card_columns(980, 1, 2), 2);
    EXPECT_EQ(monitor_card_columns(600, 1, 2), 1);
    EXPECT_EQ(monitor_card_columns(980, 1, 1), 1);
    EXPECT_EQ(monitor_card_columns(1470, 1.5, 2), 2);
    EXPECT_EQ(monitor_card_columns(900, 1.5, 2), 1);
}

TEST(MonitorModel, CompactThenShowsOnlyItsCurrentStepAndNoChildrenWhenComplete) {
    ConditionDiagnosticsNode node;
    node.type = "then";
    node.active_step = 1;
    node.children.resize(3);
    node.children[0].type = "detected";
    node.children[1].type = "all";
    node.children[1].children.resize(2);
    node.children[2].type = "elapsed";
    auto row = compact_condition_row(node);
    EXPECT_NE(row.label.find("2 / 3"), std::string::npos);
    auto children = compact_condition_children(row);
    ASSERT_EQ(children.size(), 2);
    EXPECT_EQ(row.branch, &node.children[1]);
    EXPECT_EQ(children[0].condition, &node.children[1].children[0]);
    EXPECT_NE(row.label.find("all"), std::string::npos);
    node.completed = true;
    node.active_step.reset();
    row = compact_condition_row(node);
    EXPECT_TRUE(compact_condition_children(row).empty());
    EXPECT_NE(row.label.find("Complete 3 / 3"), std::string::npos);
    node.completed = false;
    node.active_step = 0;
    row = compact_condition_row(node);
    EXPECT_TRUE(compact_condition_children(row).empty());
}

TEST(MonitorModel, WrapperAroundABranchKeepsHierarchyAndResetWhenRoles) {
    ConditionDiagnosticsNode hold;
    hold.type = "hold";
    hold.children.resize(1);
    hold.children[0].type = "any";
    hold.children[0].children.resize(2);
    const auto row = compact_condition_row(hold);
    EXPECT_EQ(compact_condition_children(row).size(), 2);
    ConditionDiagnosticsNode reset;
    reset.type = "reset_when";
    reset.children.resize(2);
    const auto roles = compact_condition_children(compact_condition_row(reset));
    ASSERT_EQ(roles.size(), 2);
    EXPECT_EQ(roles[0].role, "Condition");
    EXPECT_EQ(roles[1].role, "Reset");
}

TEST(MonitorModel, InspectorRetainsPastSequenceRulesAndAllThenSteps) {
    ScenarioCardModel card;
    RuleDiagnosticsNode sequence;
    sequence.path = "split.0.r0";
    sequence.active_rule_index = 1;
    for (int i = 0; i < 3; ++i) {
        RuleDiagnosticsNode rule;
        rule.index = static_cast<std::size_t>(i);
        rule.condition.type = "then";
        rule.condition.path = sequence.path + ".s" + std::to_string(i) + ".cond";
        rule.condition.active_step = 1;
        for (int j = 0; j < 3; ++j) {
            ConditionDiagnosticsNode child;
            child.type = "detected";
            child.path = rule.condition.path + ".c" + std::to_string(j);
            rule.condition.children.push_back(child);
        }
        sequence.sequence_rules.push_back(rule);
    }
    card.rule_groups.push_back({"Split 1", {sequence}, "split.0", true});
    const auto& source = card.rule_groups[0].rules[0];
    EXPECT_EQ(compact_sequence_rule(source), &source.sequence_rules[1]);
    const auto roots = inspector_rule_roots(card);
    ASSERT_EQ(roots.size(), 3);
    EXPECT_FALSE(roots[0].current);
    EXPECT_TRUE(roots[1].current);
    EXPECT_NE(find_condition(card, roots[0].condition->children[0].path), nullptr);
    EXPECT_FALSE(condition_is_current(card, roots[0].condition->children[1].path));
    EXPECT_FALSE(condition_is_current(card, roots[1].condition->children[0].path));
    EXPECT_TRUE(condition_is_current(card, roots[1].condition->children[1].path));
    EXPECT_FALSE(condition_is_current(card, roots[1].condition->children[2].path));
}

TEST(HistoryPlot, SharedChartNormalizesSeparateSeriesAndPreservesBoundaries) {
    using namespace std::chrono_literals;
    const auto sample = [](int t, std::optional<double> value, HistoryEvent event = HistoryEvent::sample,
                           std::optional<bool> state = false) {
        return EvaluationSample{{t * 1'000'000'000LL}, value, ConditionStatus::false_value, event, state};
    };
    ConditionDiagnosticsNode hold;
    hold.path = "hold"; hold.type = "hold"; hold.measurement.target = 2;
    ConditionDiagnosticsNode score;
    score.path = "score"; score.type = "detected"; score.measurement.target = 0.5;
    ConditionDiagnosticsNode boolean;
    boolean.path = "zero"; boolean.type = "detected"; boolean.measurement.target = 0;
    const ConditionHistory h{"hold", {sample(1, 1), sample(2, 0, HistoryEvent::transition),
        sample(3, {}, HistoryEvent::gap, {}), sample(4, 2), sample(5, {}, HistoryEvent::reset, {}),
        sample(6, {}, HistoryEvent::error, {})}, MonotonicTime{6'000'000'000}};
    const ConditionHistory d{"score", {sample(1, 0.25), sample(2, 0.9)}, MonotonicTime{2'000'000'000}};
    const ConditionHistory z{"zero", {sample(1, 7, HistoryEvent::sample, false),
        sample(2, 8, HistoryEvent::sample, true)}, MonotonicTime{2'000'000'000}};
    const auto chart = prepare_shared_chart({{&hold, &h, false}, {&score, &d, true}, {&boolean, &z, true}},
                                           {6'000'000'000}, 15s, {{5'500'000'000}});
    ASSERT_EQ(chart.series.size(), 3);
    EXPECT_EQ(chart.series[0].path, "hold");
    ASSERT_EQ(chart.series[0].segments.size(), 2);
    const auto& drop = chart.series[0].segments[0];
    ASSERT_EQ(drop.size(), 3);
    EXPECT_FLOAT_EQ(drop[0].value, 0.5f);
    EXPECT_EQ(drop[1].time, drop[2].time);
    EXPECT_FLOAT_EQ(drop[2].value, 0);
    EXPECT_FLOAT_EQ(chart.series[0].segments[1][0].value, 1);
    EXPECT_EQ(chart.series[1].path, "score");
    EXPECT_FLOAT_EQ(chart.series[1].segments[0][0].value, 0.5f);
    EXPECT_FLOAT_EQ(chart.series[1].segments[0].back().value, 1.25f);
    EXPECT_EQ(d.samples.back().value, 0.9);
    EXPECT_TRUE(chart.series[2].segments.empty());
    ASSERT_EQ(chart.series[2].states.size(), 2);
    EXPECT_EQ(chart.series[2].states[0].value, 0);
    EXPECT_EQ(chart.series[2].states[1].value, 1);
    for (const auto kind : {SharedMarkerKind::reset, SharedMarkerKind::error,
                            SharedMarkerKind::transition, SharedMarkerKind::timer_reset})
        EXPECT_NE(std::ranges::find(chart.markers, kind, &SharedHistoryMarker::kind), chart.markers.end());
}

TEST(HistoryPlot, SharedRepresentativesStayFixedAcrossPollsAndSeriesCount) {
    using namespace std::chrono_literals;
    ConditionDiagnosticsNode score;
    score.type = "detected";
    score.path = "score";
    score.measurement.target = 1;
    ConditionHistory history;
    history.path = score.path;
    const MonotonicTime bucket_start{20'000'000'000};
    const auto record = [&](std::chrono::milliseconds offset, double value) {
        history.samples.push_back({bucket_start + offset, value, ConditionStatus::false_value, HistoryEvent::sample, false});
    };
    record(20ms, 0.4);
    record(65ms, 0.8);
    record(130ms, 0.6);
    record(210ms, 0.1);
    record(450ms, 0.5);
    history.samples.push_back({bucket_start + 470ms, {}, ConditionStatus::not_evaluated, HistoryEvent::reset, {}});
    const std::vector<SharedHistorySource> sources{{&score, &history, true}};
    const auto first = prepare_shared_chart(sources, bucket_start + 600ms, 15s, {});
    ASSERT_EQ(first.series.front().segments.size(), 1);
    const std::vector<SharedHistoryPoint> expected{{bucket_start + 20ms, 0.4f}, {bucket_start + 65ms, 0.8f},
        {bucket_start + 210ms, 0.1f}, {bucket_start + 450ms, 0.5f}};
    EXPECT_EQ(first.series.front().segments.front(), expected);
    const auto later = prepare_shared_chart(sources, bucket_start + 770ms, 15s, {});
    EXPECT_EQ(later.series.front().segments, first.series.front().segments);
    EXPECT_EQ(later.markers, first.markers);
    const auto at_left_edge = prepare_shared_chart(sources, bucket_start + 15s + 200ms, 15s, {});
    EXPECT_EQ(at_left_edge.series.front().segments, first.series.front().segments);

    auto crowded = sources;
    std::vector<ConditionDiagnosticsNode> peers(80, score);
    for (std::size_t i = 0; i < peers.size(); ++i) {
        peers[i].path = "peer." + std::to_string(i);
        crowded.push_back({&peers[i], &history, true});
    }
    const auto more = prepare_shared_chart(crowded, bucket_start + 770ms, 15s, {});
    EXPECT_EQ(more.series.front().segments, first.series.front().segments);
    EXPECT_EQ(more.markers, first.markers);

    record(810ms, 0.2);
    const auto appended = prepare_shared_chart(sources, bucket_start + 900ms, 15s, {});
    ASSERT_EQ(appended.series.front().segments.size(), 2);
    EXPECT_EQ(appended.series.front().segments.front(), expected);
    EXPECT_EQ(appended.series.front().segments.back().back(), (SharedHistoryPoint{bucket_start + 810ms, 0.2f}));
}

TEST(HistoryPlot, SharedWindowsUseTheSameAbsolutePointsAndKeepNthStepsVertical) {
    using namespace std::chrono_literals;
    ConditionDiagnosticsNode nth;
    nth.type = "nth";
    nth.path = "nth";
    nth.measurement = {{}, 10, "count", true};
    ConditionHistory history;
    history.path = nth.path;
    for (const auto [seconds, count] : {std::pair{10, 1.0}, {35, 3.0}, {50, 5.0}, {59, 6.0}})
        history.samples.push_back({MonotonicTime{} + std::chrono::seconds{seconds}, count,
            ConditionStatus::false_value, HistoryEvent::sample, false});
    const std::vector<SharedHistorySource> sources{{&nth, &history, true}};
    for (const auto [window, first] : {std::pair{15s, 50s}, {30s, 35s}, {60s, 10s}}) {
        const auto chart = prepare_shared_chart(sources, MonotonicTime{} + 60s, window, {});
        EXPECT_EQ(chart.seconds, window.count());
        const auto& points = chart.series.front().segments.front();
        ASSERT_GE(points.size(), 3);
        EXPECT_EQ(points.front().time, MonotonicTime{} + first);
        EXPECT_EQ(points[points.size() - 2].time, MonotonicTime{} + 59s);
        EXPECT_EQ(points.back().time, MonotonicTime{} + 59s);
        EXPECT_FLOAT_EQ(points[points.size() - 2].value, 0.5f);
        EXPECT_FLOAT_EQ(points.back().value, 0.6f);
    }
}

TEST(MonitorModel, SharedChartKeepsPastStartAndThenStepWhileResetStaysSeparate) {
    using namespace std::chrono_literals;
    ScenarioCardModel card;
    auto history = std::make_shared<EvaluationHistorySnapshot>();
    history->sampled_at = {30'000'000'000};
    card.history = history;
    const auto node = [&](const std::string& path, MonotonicTime time) {
        ConditionDiagnosticsNode condition;
        condition.type = "detected";
        condition.path = path;
        condition.measurement.target = 0.5;
        history->conditions.push_back({path,
            {{time, 0.25, ConditionStatus::false_value, HistoryEvent::sample, false}}, time});
        return condition;
    };
    RuleDiagnosticsNode start, split, reset, expired;
    start.condition = node("start.r0.cond", {19'000'000'000});
    reset.condition = node("reset.r0.cond", {28'000'000'000});
    expired.condition = node("split.1.r0.cond", {1'000'000'000});
    split.condition.path = "split.0.r0.cond";
    split.condition.type = "then";
    split.condition.active_step = 0;
    split.condition.children = {node("split.0.r0.cond.c0", {22'000'000'000}),
                                node("split.0.r0.cond.c1", {29'000'000'000})};
    card.rule_groups = {{"Start", {start}, "start", true}, {"Split 1", {split}, "split.0", false},
                        {"Reset", {reset}, "reset", false}, {"Split 2", {expired}, "split.1", false}};
    const auto palette = theme::colors(theme::Mode::dark);
    const auto before = shared_history_groups(card, 15s);
    ASSERT_EQ(before.normal.size(), 3);
    EXPECT_TRUE(before.normal.front().current);
    const auto before_chart = prepare_shared_chart(before.normal, history->sampled_at, 15s, {});
    const auto color = shared_series_color(before.normal.front().condition->path, palette);
    card.rule_groups[0].current = false;
    card.rule_groups[1].current = true;
    card.rule_groups[1].rules[0].condition.active_step = 1;
    card.rule_groups[2].current = true;
    // The active step may skip a frame while another branch short-circuits.
    auto& step_two = history->conditions.back();
    step_two.samples.push_back({{30'000'000'000}, {}, ConditionStatus::skipped, HistoryEvent::gap, {}});
    card.rule_groups[1].rules[0].condition.children[1].status = "skipped";
    const auto after = shared_history_groups(card, 15s);
    ASSERT_EQ(after.normal.size(), 3);
    ASSERT_EQ(after.reset.size(), 1);
    EXPECT_EQ(after.reset.front().condition->path, "reset.r0.cond");
    EXPECT_FALSE(after.normal[0].current);
    EXPECT_FALSE(after.normal[1].current);
    EXPECT_TRUE(after.normal[2].current);
    const auto after_chart = prepare_shared_chart(after.normal, history->sampled_at, 15s, {});
    for (const auto& line : before_chart.series) {
        const auto found = std::ranges::find(after_chart.series, line.path, &SharedHistorySeries::path);
        ASSERT_NE(found, after_chart.series.end());
        EXPECT_EQ(found->segments, line.segments);
    }
    const auto same_color = shared_series_color(after.normal.front().condition->path, palette);
    EXPECT_FLOAT_EQ(color.x, same_color.x);
    EXPECT_FLOAT_EQ(color.y, same_color.y);
    EXPECT_FLOAT_EQ(color.z, same_color.z);
    const auto other = shared_series_color(after.normal[2].condition->path, palette);
    EXPECT_NE(ImGui::ColorConvertFloat4ToU32(color), ImGui::ColorConvertFloat4ToU32(other));
    EXPECT_EQ(shared_history_groups(card, 60s).normal.size(), 4);
}

TEST(HistoryPlot, StatusIconsHaveDistinctShapesInBothThemesWithoutAddingHeight) {
    for (const auto mode : {theme::Mode::dark, theme::Mode::light}) {
        for (const float scale : {1.0f, 1.5f}) {
            PlotFixture fixture;
            ConditionDiagnosticsNode node;
            node.type = "detected";
            node.path = "condition";
            const auto draw = [&](const char* status) {
                node.status = status;
                fixture.begin();
                ImGui::PushStyleVar(ImGuiStyleVar_ItemSpacing, ImVec2(4 * scale, 2 * scale));
                std::vector<std::pair<float, float>> geometry;
                auto* draw_list = ImGui::GetWindowDrawList();
                const int first = draw_list->VtxBuffer.Size;
                const float top = ImGui::GetCursorScreenPos().y;
                draw_compact_condition_row(compact_condition_row(node), false, 0, {}, false,
                    theme::colors(mode), scale);
                for (int i = first; i < draw_list->VtxBuffer.Size; ++i) {
                    const auto& pos = draw_list->VtxBuffer[i].pos;
                    geometry.emplace_back(pos.x, pos.y);
                }
                EXPECT_LE(ImGui::GetCursorScreenPos().y - top, 28 * scale);
                ImGui::PopStyleVar();
                fixture.end();
                return geometry;
            };
            (void)draw("false"); // Stabilize the window before comparing geometry.
            (void)draw("false");
            std::vector<std::vector<std::pair<float, float>>> shapes;
            for (const auto* status : {"true", "false", "not_evaluated", "skipped", "error"}) {
                auto shape = draw(status);
                ASSERT_FALSE(shape.empty());
                for (const auto& previous : shapes) EXPECT_NE(shape, previous) << status;
                shapes.push_back(std::move(shape));
            }
        }
    }
}

TEST(HistoryPlot, SharedDrawFramesTranslateTheSameCachedTrace) {
    PlotFixture fixture;
    SharedHistoryChart chart;
    chart.seconds = 30;
    chart.series = {{"clocked", true, 60,
        {{{{40'000'000'000}, 0.3f}, {{45'000'000'000}, 0.7f}, {{50'000'000'000}, 0.2f}}}, {}}};
    const auto palette = theme::colors(theme::Mode::dark);
    const auto ink = ImGui::ColorConvertFloat4ToU32(shared_series_color("clocked", palette));
    const auto draw = [&](double now) {
        fixture.begin();
        draw_shared_chart("shared", chart, now, 30, {300, 120}, palette, 1);
        std::vector<ImVec2> vertices;
        for (const auto& vertex : ImGui::GetWindowDrawList()->VtxBuffer)
            if (vertex.col == ink) vertices.push_back(vertex.pos);
        fixture.end();
        return vertices;
    };
    (void)draw(60);
    const auto first = draw(60);
    const auto next = draw(60.05);
    ASSERT_GE(first.size(), 3);
    ASSERT_EQ(first.size(), next.size());
    for (std::size_t i = 0; i < first.size(); ++i) {
        EXPECT_NEAR(first[i].x - next[i].x, (300 - 14) * 0.05 / 30, 0.001);
        EXPECT_NEAR(first[i].y, next[i].y, 0.001);
    }
}

TEST(HistoryPlot, SharedGraphClickSelectsAVisibleHistoricalTrace) {
    using namespace std::chrono_literals;
    PlotFixture fixture;
    SharedHistoryChart chart;
    chart.seconds = 30;
    chart.series = {{"past", false, 60, {{{{35'000'000'000}, 0.5f}, {{55'000'000'000}, 0.5f}}}, {}},
                    {"current", true, 60, {{{{35'000'000'000}, 1.2f}, {{55'000'000'000}, 1.2f}}}, {}}};
    const auto palette = theme::colors(theme::Mode::dark);
    ImVec2 hit;
    const auto draw = [&] {
        fixture.begin();
        const auto origin = ImGui::GetCursorScreenPos();
        hit = {origin.x + 140, origin.y + 58};
        const auto result = draw_shared_chart("shared", chart, 60, 30, {300, 120}, palette, 1);
        fixture.end();
        return result;
    };
    EXPECT_FALSE(draw().clicked);
    ImGui::GetIO().AddMousePosEvent(hit.x, hit.y);
    (void)draw();
    ImGui::GetIO().AddMouseButtonEvent(ImGuiMouseButton_Left, true);
    const auto clicked = draw();
    EXPECT_TRUE(clicked.clicked);
    EXPECT_EQ(clicked.path, "past");
}
