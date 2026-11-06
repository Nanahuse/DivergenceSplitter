#pragma once

#include <chrono>
#include <map>
#include <vector>

#include "image_texture.hpp"
#include "monitor_model.hpp"

namespace divergencesplitter::ui {

class App;

class MonitorPage {
public:
    explicit MonitorPage(App* app);

    void update(double now);
    void draw();

private:
    struct EvaluationRate {
        std::uint64_t generation{};
        std::uint64_t count{};
        std::chrono::steady_clock::time_point sampled_at;
        double fps{};
    };

    struct Data {
        bool running{};
        std::uint64_t frames_published{};
        double measured_fps{};
        double processing_fps{};
        std::string last_error;
        std::vector<ScenarioCardModel> cards;
    };

    void draw_status_rows();
    void draw_cards();
    void draw_reset_button();
    void draw_card(const ScenarioCardModel& card);

    App* app_;
    ImageTexture preview_;
    Data data_;
    double next_update_{};
    std::map<int, EvaluationRate> evaluation_rates_;
    bool reset_holding_{};
    bool reset_triggered_{};
    double reset_started_{};
};

}  // namespace divergencesplitter::ui
