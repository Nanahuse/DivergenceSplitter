#include <gtest/gtest.h>
#include <imgui.h>
#include <implot.h>

#include "history_plot.hpp"
#include "monitor_model.hpp"

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
