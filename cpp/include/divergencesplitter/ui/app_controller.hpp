#pragma once

#include <QObject>
#include <QString>

#include "divergencesplitter/configuration/configuration.hpp"
#include "divergencesplitter/runtime/session.hpp"

namespace divergencesplitter::ui {

class AppController final : public QObject {
    Q_OBJECT

public:
    explicit AppController(QObject* parent = nullptr);
    ~AppController() override;

    [[nodiscard]] const AppSettings& settings() const noexcept { return settings_; }
    [[nodiscard]] Profile profile() const;
    [[nodiscard]] Session& session() noexcept { return session_; }
    [[nodiscard]] const Session& session() const noexcept { return session_; }

    bool apply_profile(const Profile& profile, QString* error);
    bool open_profile(const std::filesystem::path& path, QString* error);
    bool save_profile_file(const std::filesystem::path& path, const Profile& profile, QString* error);
    void save_settings(const AppSettings& settings, QString* error);
    [[nodiscard]] std::optional<std::filesystem::path> profile_path() const;
    void stop();
    void request_reset_all();
    [[nodiscard]] QString last_error() const;

private:
    [[nodiscard]] QString load_initial_profile();

    AppSettings settings_;
    Profile profile_;
    std::optional<std::filesystem::path> profile_path_;
    Session session_;
};

}  // namespace divergencesplitter::ui
