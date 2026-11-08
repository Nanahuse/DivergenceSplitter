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
        EXPECT_EQ(row.graph, root.type == "not" ? &root.children[0] : &root);
        EXPECT_EQ(root.children.size(), 1);
    }
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
    EXPECT_EQ(row.graph, nullptr);
    EXPECT_NE(row.label.find("2 / 3"), std::string::npos);
    auto children = compact_condition_children(row);
    ASSERT_EQ(children.size(), 1);
    EXPECT_EQ(children[0].condition, &node.children[1]);
    EXPECT_EQ(compact_condition_children(compact_condition_row(*children[0].condition)).size(), 2);
    node.completed = true;
    node.active_step.reset();
    row = compact_condition_row(node);
    EXPECT_TRUE(compact_condition_children(row).empty());
    EXPECT_NE(row.label.find("Complete 3 / 3"), std::string::npos);
    node.completed = false;
    node.active_step = 0;
    EXPECT_EQ(compact_condition_children(compact_condition_row(node))[0].condition, &node.children[0]);
}

TEST(MonitorModel, WrapperAroundABranchKeepsHierarchyAndResetWhenRoles) {
    ConditionDiagnosticsNode hold;
    hold.type = "hold";
    hold.children.resize(1);
    hold.children[0].type = "any";
    hold.children[0].children.resize(2);
    const auto row = compact_condition_row(hold);
    EXPECT_EQ(row.graph, &hold);
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

TEST(HistoryPlot, SparklineRetainsGapsResetsErrorsAndVerticalHoldDrops) {
    EvaluationHistorySnapshot history;
    history.conditions.push_back({"hold", {
        {{1'000'000'000}, 0.5, ConditionStatus::false_value, HistoryEvent::sample, false},
        {{2'000'000'000}, 0.0, ConditionStatus::false_value, HistoryEvent::transition, false},
        {{3'000'000'000}, {}, ConditionStatus::skipped, HistoryEvent::gap, {}},
        {{4'000'000'000}, 0.2, ConditionStatus::false_value, HistoryEvent::sample, false},
        {{5'000'000'000}, {}, ConditionStatus::not_evaluated, HistoryEvent::reset, {}},
        {{6'000'000'000}, {}, ConditionStatus::error, HistoryEvent::error, {}}
    }});
    ConditionDiagnosticsNode node;
    node.path = "hold";
    node.measurement.target = 1.0;
    const auto plots = prepare_history(history, {"hold"});
    const auto geometry = sparkline_geometry(node, plots.at("hold"), 6, 6, ImVec2(140, 22));
    ASSERT_EQ(geometry.segments.size(), 2);
    const auto& points = geometry.segments[0].points;
    ASSERT_GE(points.size(), 3);
    EXPECT_FLOAT_EQ(points[1].x, points[2].x);
    EXPECT_LT(points[1].y, points[2].y);
    EXPECT_EQ(geometry.resets.size(), 1);
    EXPECT_EQ(geometry.errors.size(), 1);
    EXPECT_TRUE(geometry.target.has_value());
}

TEST(HistoryPlot, CompactRowsStayWithinOneLineAndTheSparklineIsClickable) {
    PlotFixture fixture;
    ConditionDiagnosticsNode hold;
    hold.type = "hold";
    hold.path = "hold";
    hold.status = "false";
    hold.children.resize(1);
    hold.children[0].type = "detected";
    ImVec2 hit;
    const auto draw = [&] {
        fixture.begin();
        const float top = ImGui::GetCursorScreenPos().y;
        ImGui::PushStyleVar(ImGuiStyleVar_CellPadding, ImVec2(4, 1));
        ImGui::PushStyleVar(ImGuiStyleVar_FramePadding, ImVec2(4, 2));
        const ConditionDiagnosticsNode* selected = nullptr;
        if (ImGui::BeginTable("rows", 3)) {
            ImGui::TableSetupColumn("state", ImGuiTableColumnFlags_WidthFixed, 18);
            ImGui::TableSetupColumn("name", ImGuiTableColumnFlags_WidthStretch);
            ImGui::TableSetupColumn("history", ImGuiTableColumnFlags_WidthFixed, 140);
            for (int i = 0; i < 10; ++i) {
                ImGui::PushID(i);
                auto action = draw_compact_condition_row(compact_condition_row(hold), false, 0, {}, false,
                    fixture.history, 60, 30, theme::colors(theme::Mode::dark), 1);
                if (i == 0) {
                    const auto min = ImGui::GetItemRectMin(), max = ImGui::GetItemRectMax();
                    hit = ImVec2((min.x + max.x)/2, (min.y + max.y)/2);
                }
                if (action.selected) selected = action.selected;
                ImGui::PopID();
            }
            ImGui::EndTable();
        }
        ImGui::PopStyleVar(2);
        EXPECT_LE(ImGui::GetCursorScreenPos().y - top, 260);
        fixture.end();
        return selected;
    };
    EXPECT_EQ(draw(), nullptr);
    ImGui::GetIO().AddMousePosEvent(hit.x, hit.y);
    (void)draw();
    ImGui::GetIO().AddMouseButtonEvent(ImGuiMouseButton_Left, true);
    EXPECT_EQ(draw(), &hold);
}
