#pragma once

#include <string>

namespace divergencesplitter::ui {

class App;

class SettingsPage {
public:
    explicit SettingsPage(App* app);

    void reload();
    void draw();

private:
    void save();

    App* app_;
    int theme_index_{};
    int reaction_time_ms_{};
    int log_level_index_{};
    std::string status_;
};

}  // namespace divergencesplitter::ui
