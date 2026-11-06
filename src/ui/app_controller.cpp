#include "app_controller.hpp"

#include <exception>

#include "divergencesplitter/text.hpp"

namespace divergencesplitter::ui {

AppController::AppController() {
    try {
        const auto path = default_settings_path();
        if (std::filesystem::exists(path)) {
            settings_ = load_app_settings(path);
        }
    } catch (const std::exception&) {
        settings_ = AppSettings{};
    }

    load_initial_profile();
}

AppController::~AppController() {
    session_.stop();
}

void AppController::load_initial_profile() {
    if (!settings_.last_profile.has_value()) {
        return;
    }
    const auto path = path_from_utf8(*settings_.last_profile);
    if (std::filesystem::exists(path)) {
        std::string ignored;
        open_profile(path, &ignored);
    }
}

Profile AppController::profile() const {
    return profile_;
}

bool AppController::apply_profile(const Profile& profile, std::string* error) {
    try {
        session_.apply_profile(profile, settings_);
        profile_ = profile;
        return true;
    } catch (const std::exception& failure) {
        if (error != nullptr) {
            *error = failure.what();
        }
        return false;
    }
}

bool AppController::open_profile(const std::filesystem::path& path, std::string* error) {
    try {
        auto loaded = load_profile(path);
        session_.apply_profile(loaded.profile, settings_);
        profile_ = loaded.profile;
        profile_path_ = path;
        settings_.last_profile = path_to_utf8(path);
        try {
            save_app_settings(default_settings_path(), settings_);
        } catch (const std::exception&) {
            // The profile itself opened successfully; remember it next time if possible.
        }
        return true;
    } catch (const std::exception& failure) {
        if (error != nullptr) {
            *error = failure.what();
        }
        return false;
    }
}

bool AppController::save_profile_file(
    const std::filesystem::path& path,
    const Profile& profile,
    std::string* error
) {
    try {
        save_profile(path, profile);
        profile_path_ = path;
        settings_.last_profile = path_to_utf8(path);
        try {
            save_app_settings(default_settings_path(), settings_);
        } catch (const std::exception&) {
            // The profile file was written; a settings-file failure must not report it lost.
        }
        return true;
    } catch (const std::exception& failure) {
        if (error != nullptr) {
            *error = failure.what();
        }
        return false;
    }
}

void AppController::save_settings(const AppSettings& settings, std::string* error) {
    try {
        const auto previous_profile = settings_.last_profile;
        settings_ = settings;
        if (!settings_.last_profile.has_value()) {
            settings_.last_profile = previous_profile;
        }
        save_app_settings(default_settings_path(), settings_);
    } catch (const std::exception& failure) {
        if (error != nullptr) {
            *error = failure.what();
        }
    }
}

std::optional<std::filesystem::path> AppController::profile_path() const {
    return profile_path_;
}

void AppController::stop() {
    session_.stop();
}

void AppController::request_reset_all() {
    session_.request_reset_all();
}

std::string AppController::last_error() const {
    return session_.last_error();
}

}  // namespace divergencesplitter::ui
