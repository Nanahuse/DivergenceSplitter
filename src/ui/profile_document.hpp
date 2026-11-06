#pragma once

#include <filesystem>
#include <optional>

#include "divergencesplitter/configuration/configuration.hpp"

namespace divergencesplitter::ui {

[[nodiscard]] inline Profile default_profile() {
    Profile profile;
    auto& camera = std::get<CameraSourceConfiguration>(profile.source);
    camera.mode.width = 1920;
    camera.mode.height = 1080;
    camera.mode.fps = 60.0;
    return profile;
}

// Keeps the editable, saved, and runtime-applied states distinct.
// Apply updates the runtime without touching saved; Save updates saved without
// touching the runtime. The controller owns the applied Profile.
class ProfileDocument {
public:
    Profile draft;
    std::optional<Profile> saved;
    std::optional<std::filesystem::path> path;

    [[nodiscard]] bool dirty() const {
        return !saved.has_value() || draft != *saved;
    }

    void start_new(std::filesystem::path new_path) {
        draft = default_profile();
        saved.reset();
        path = std::move(new_path);
    }

    void adopt_saved(Profile profile, std::filesystem::path saved_path) {
        draft = profile;
        saved = std::move(profile);
        path = std::move(saved_path);
    }

    void mark_saved(const Profile& profile, std::filesystem::path saved_path) {
        saved = profile;
        path = std::move(saved_path);
    }

    void revert_draft(const Profile& applied) {
        draft = saved.has_value() ? *saved : applied;
    }
};

}  // namespace divergencesplitter::ui
