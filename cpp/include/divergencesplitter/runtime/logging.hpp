#pragma once

#include <cstdint>
#include <filesystem>
#include <mutex>
#include <string>
#include <string_view>

namespace divergencesplitter {

enum class LogLevel {
    off,
    debug,
    info,
    warning,
    error,
};

[[nodiscard]] LogLevel parse_log_level(std::string_view value) noexcept;
[[nodiscard]] std::string_view to_string(LogLevel level) noexcept;

class Logger {
public:
    Logger(std::filesystem::path path, LogLevel level, std::uintmax_t max_bytes = 1024 * 1024);

    void log(LogLevel level, std::string_view event, std::string_view message = {});
    [[nodiscard]] bool enabled(LogLevel level) const noexcept;

private:
    void rotate_locked();

    std::filesystem::path path_;
    LogLevel level_{LogLevel::off};
    std::uintmax_t max_bytes_;
    mutable std::mutex mutex_;
};

}  // namespace divergencesplitter
