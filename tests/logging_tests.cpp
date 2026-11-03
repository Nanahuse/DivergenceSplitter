#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>

#include "divergencesplitter/runtime/logging.hpp"

using namespace divergencesplitter;

namespace {

class TemporaryDirectory {
public:
    TemporaryDirectory() {
        static int counter = 0;
        path_ = std::filesystem::temp_directory_path() /
                ("divergencesplitter-log-" + std::to_string(++counter) + "-" +
                 std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directories(path_);
    }
    ~TemporaryDirectory() {
        std::error_code error;
        std::filesystem::remove_all(path_, error);
    }
    [[nodiscard]] const std::filesystem::path& path() const { return path_; }

private:
    std::filesystem::path path_;
};

}  // namespace

TEST(Logging, LevelFiltering) {
    TemporaryDirectory directory;
    Logger logger(directory.path() / "test.log", LogLevel::warning);
    EXPECT_FALSE(logger.enabled(LogLevel::debug));
    EXPECT_FALSE(logger.enabled(LogLevel::info));
    EXPECT_TRUE(logger.enabled(LogLevel::warning));
    EXPECT_TRUE(logger.enabled(LogLevel::error));
    logger.log(LogLevel::info, "hidden");
    logger.log(LogLevel::warning, "visible", "message");

    std::ifstream stream{directory.path() / "test.log"};
    const std::string content{
        std::istreambuf_iterator<char>(stream),
        std::istreambuf_iterator<char>()
    };
    EXPECT_EQ(content.find("hidden"), std::string::npos);
    EXPECT_NE(content.find("visible"), std::string::npos);
}

TEST(Logging, RotatesAtSizeLimit) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "diagnostics.log";
    Logger logger(path, LogLevel::info, 80);
    for (int index = 0; index < 20; ++index) {
        logger.log(LogLevel::info, "rotation", std::string(40, 'x'));
    }
    EXPECT_TRUE(std::filesystem::exists(path));
    EXPECT_TRUE(std::filesystem::exists(path.string() + ".1"));
}

TEST(Logging, ParsesConfigurationNames) {
    EXPECT_EQ(parse_log_level("OFF"), LogLevel::off);
    EXPECT_EQ(parse_log_level("DEBUG"), LogLevel::debug);
    EXPECT_EQ(parse_log_level("INFO"), LogLevel::info);
    EXPECT_EQ(parse_log_level("WARNING"), LogLevel::warning);
    EXPECT_EQ(parse_log_level("ERROR"), LogLevel::error);
}
