#include "divergencesplitter/runtime/logging.hpp"

#include <chrono>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <sstream>

namespace divergencesplitter {
namespace {

std::string timestamp() {
    const auto now = std::chrono::system_clock::now();
    const auto time = std::chrono::system_clock::to_time_t(now);
    std::tm local{};
#ifdef _WIN32
    localtime_s(&local, &time);
#else
    localtime_r(&time, &local);
#endif
    std::ostringstream stream;
    stream << std::put_time(&local, "%Y-%m-%dT%H:%M:%S");
    return stream.str();
}

}  // namespace

LogLevel parse_log_level(std::string_view value) noexcept {
    if (value == "OFF") {
        return LogLevel::off;
    }
    if (value == "DEBUG") {
        return LogLevel::debug;
    }
    if (value == "WARNING") {
        return LogLevel::warning;
    }
    if (value == "ERROR") {
        return LogLevel::error;
    }
    return LogLevel::info;
}

std::string_view to_string(LogLevel level) noexcept {
    switch (level) {
        case LogLevel::off:
            return "OFF";
        case LogLevel::debug:
            return "DEBUG";
        case LogLevel::info:
            return "INFO";
        case LogLevel::warning:
            return "WARNING";
        case LogLevel::error:
            return "ERROR";
    }
    return "INFO";
}

Logger::Logger(std::filesystem::path path, LogLevel level, std::uintmax_t max_bytes)
    : path_(std::move(path)), level_(level), max_bytes_(max_bytes) {
    if (path_.has_parent_path()) {
        std::error_code error;
        std::filesystem::create_directories(path_.parent_path(), error);
    }
}

bool Logger::enabled(LogLevel level) const noexcept {
    return level_ != LogLevel::off && static_cast<int>(level) >= static_cast<int>(level_);
}

void Logger::log(LogLevel level, std::string_view event, std::string_view message) {
    if (!enabled(level)) {
        return;
    }
    std::scoped_lock lock{mutex_};
    std::error_code size_error;
    const auto size = std::filesystem::file_size(path_, size_error);
    if (!size_error && size >= max_bytes_) {
        rotate_locked();
    }
    std::ofstream stream{path_, std::ios::binary | std::ios::app};
    if (!stream) {
        return;
    }
    stream << timestamp() << " [" << to_string(level) << "] " << event;
    if (!message.empty()) {
        stream << ": " << message;
    }
    stream << '\n';
}

void Logger::rotate_locked() {
    std::error_code error;
    for (int index = 2; index >= 1; --index) {
        const auto source = path_.string() + "." + std::to_string(index);
        const auto target = path_.string() + "." + std::to_string(index + 1);
        if (std::filesystem::exists(source, error)) {
            std::filesystem::rename(source, target, error);
        }
    }
    if (std::filesystem::exists(path_, error)) {
        std::filesystem::rename(path_, path_.string() + ".1", error);
    }
}

}  // namespace divergencesplitter
