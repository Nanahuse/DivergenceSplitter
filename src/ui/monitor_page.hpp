#pragma once

#include <chrono>
#include <map>
#include <vector>

#include "image_texture.hpp"
#include "monitor_model.hpp"
#include "history_plot.hpp"
#include <set>

namespace divergencesplitter::ui {

class App;

class MonitorPage {
public:
    explicit MonitorPage(App* app);

    void update(double now);
    void draw();

private:
    struct Data {
        bool running{};
        std::uint64_t frames_published{};
        double measured_fps{};

        std::string last_error;
        std::vector<ScenarioCardModel> cards;
    };

    void draw_status_rows();
    void draw_cards();
    void draw_reset_button();
    void draw_card(const ScenarioCardModel& card);
    void draw_rule(const RuleDiagnosticsNode& rule, const ScenarioCardModel& card);
    void draw_condition(const ConditionDiagnosticsNode& condition, const ScenarioCardModel& card,
                        int depth = 0, std::string_view role = {});
    void draw_structure(const ConditionDiagnosticsNode& node, const ScenarioCardModel& card,
                        const std::string& label, bool expand_selection);
    void open_inspector(const ScenarioCardModel& card);
    void draw_details();
    void select_condition(const ScenarioCardModel& card, const ConditionDiagnosticsNode& node);
    struct InstancePlots {
        std::uint64_t identity{};
        HistoryPlots plots;
    };
    std::map<int, InstancePlots> plots_;
    int window_seconds_{30};
    bool preview_visible_{true};
    bool details_open_{};
    int selected_instance_{};
    std::uint64_t selected_identity_{};
    std::string selected_path_;
    std::map<int, std::set<std::string>> comparisons_;
    std::map<int, std::map<std::string, bool>> current_groups_;
    PlotViewport detail_view_;
    PlotViewport comparison_view_;
    bool comparison_details_{};
    InstanceHistoryPaths requested_paths_;
    std::string inspector_root_path_;
    bool inspector_selection_changed_{};
    std::set<int> instance_details_;

    App* app_;
    ImageTexture preview_;
    Data data_;
    double next_update_{};
    double draw_time_{};
    std::map<int, MonitorEvaluationRate> evaluation_rates_;
    bool reset_holding_{};
    bool reset_triggered_{};
    double reset_started_{};
};

}  // namespace divergencesplitter::ui
