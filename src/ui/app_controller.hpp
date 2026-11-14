#pragma once

#include <filesystem>
#include <optional>
#include <string>

#include "divergencesplitter/configuration/configuration.hpp"
#include "divergencesplitter/runtime/session.hpp"

namespace divergencesplitter::ui {

class AppController {
public:
    AppController();
    ~AppController();

    AppController(const AppController&) = delete;
    AppController& operator=(const AppController&) = delete;

    [[nodiscard]] const AppSettings& settings() const noexcept { return settings_; }
    [[nodiscard]] Profile profile() const;
    [[nodiscard]] Session& session() noexcept { return session_; }
    [[nodiscard]] const Session& session() const noexcept { return session_; }

    bool apply_profile(const Profile& profile, std::string* error);
    bool open_profile(const std::filesystem::path& path, std::string* error);
    bool save_profile_file(
        const std::filesystem::path& path,
        const Profile& profile,
        std::string* error
    );
    void save_settings(const AppSettings& settings, std::string* error);
    [[nodiscard]] std::optional<std::filesystem::path> profile_path() const;
    void stop();
    void request_reset_all();
    [[nodiscard]] std::string last_error() const;

private:
    void load_initial_profile();

    AppSettings settings_;
    Profile profile_;
    std::optional<std::filesystem::path> profile_path_;
    Session session_;
};

}  // namespace divergencesplitter::ui
