#include "divergencesplitter/ui/app_controller.hpp"

#include <QString>

#include <exception>

namespace divergencesplitter::ui {

AppController::AppController(QObject* parent) : QObject(parent) {
    try {
        const auto path = default_settings_path();
        if (std::filesystem::exists(path)) {
            settings_ = load_app_settings(path);
        }
    } catch (const std::exception&) {
        settings_ = AppSettings{};
    }

    if (settings_.last_profile.has_value()) {
        const std::filesystem::path path{*settings_.last_profile};
        if (std::filesystem::exists(path)) {
            QString ignored;
            open_profile(path, &ignored);
        }
    }
}

AppController::~AppController() {
    session_.stop();
}

Profile AppController::profile() const {
    return profile_;
}

bool AppController::apply_profile(const Profile& profile, QString* error) {
    emit sessionStarting();
    try {
        session_.apply_profile(profile, settings_);
        profile_ = profile;
        if (profile_path_.has_value()) {
            settings_.last_profile = profile_path_->string();
            save_app_settings(default_settings_path(), settings_);
        }
        emit sessionChanged();
        return true;
    } catch (const std::exception& failure) {
        if (error != nullptr) {
            *error = QString::fromUtf8(failure.what());
        }
        emit sessionChanged();
        return false;
    }
}

bool AppController::open_profile(const std::filesystem::path& path, QString* error) {
    try {
        auto loaded = load_profile(path);
        emit sessionStarting();
        session_.apply_profile(loaded.profile, settings_);
        profile_ = loaded.profile;
        profile_path_ = path;
        settings_.last_profile = path.string();
        save_app_settings(default_settings_path(), settings_);
        emit sessionChanged();
        return true;
    } catch (const std::exception& failure) {
        if (error != nullptr) {
            *error = QString::fromUtf8(failure.what());
        }
        emit sessionChanged();
        return false;
    }
}

bool AppController::save_profile_file(
    const std::filesystem::path& path,
    const Profile& profile,
    QString* error
) {
    try {
        save_profile(path, profile);
        profile_path_ = path;
        settings_.last_profile = path.string();
        save_app_settings(default_settings_path(), settings_);
        return true;
    } catch (const std::exception& failure) {
        if (error != nullptr) {
            *error = QString::fromUtf8(failure.what());
        }
        return false;
    }
}

void AppController::save_settings(const AppSettings& settings, QString* error) {
    try {
        const auto previous_profile = settings_.last_profile;
        settings_ = settings;
        if (!settings_.last_profile.has_value()) {
            settings_.last_profile = previous_profile;
        }
        save_app_settings(default_settings_path(), settings_);
    } catch (const std::exception& failure) {
        if (error != nullptr) {
            *error = QString::fromUtf8(failure.what());
        }
    }
}

std::optional<std::filesystem::path> AppController::profile_path() const {
    return profile_path_;
}

void AppController::stop() {
    session_.stop();
    emit sessionChanged();
}

void AppController::request_reset_all() {
    session_.request_reset_all();
}

QString AppController::last_error() const {
    return QString::fromStdString(session_.last_error());
}

}  // namespace divergencesplitter::ui
