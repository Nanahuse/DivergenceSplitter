#include <gtest/gtest.h>

#include <filesystem>
#include <fstream>
#include <string>

#include "divergencesplitter/configuration/configuration.hpp"

using namespace divergencesplitter;

namespace {

class TemporaryDirectory {
public:
    TemporaryDirectory() {
        static int counter = 0;
        path_ = std::filesystem::temp_directory_path() /
                ("divergencesplitter-test-" + std::to_string(++counter) + "-" +
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

void write_text(const std::filesystem::path& path, const std::string& text) {
    std::ofstream stream{path, std::ios::binary};
    stream << text;
}

}  // namespace

TEST(Profile, RoundTripsVersion2) {
    TemporaryDirectory directory;
    const auto scenario_path = (directory.path() / "scenario.yaml").generic_string();
    const auto video_path = (directory.path() / "run.mp4").generic_string();
    Profile profile;
    profile.source = VideoSourceConfiguration{video_path, {}};
    profile.instances.push_back(InstanceConfiguration{{54000}, scenario_path});
    profile.instances.push_back(InstanceConfiguration{{54001}, scenario_path});

    const auto path = directory.path() / "profile.json";
    save_profile(path, profile);
    const auto loaded = load_profile(path);
    EXPECT_FALSE(loaded.migrated);
    EXPECT_EQ(loaded.profile.version, 2);
    ASSERT_TRUE(std::holds_alternative<VideoSourceConfiguration>(loaded.profile.source));
    EXPECT_EQ(std::get<VideoSourceConfiguration>(loaded.profile.source).path, video_path);
    ASSERT_EQ(loaded.profile.instances.size(), 2U);
    EXPECT_EQ(loaded.profile.instances[0].connection.port, 54000);
    EXPECT_EQ(loaded.profile.instances[1].connection.port, 54001);
}

TEST(Profile, MigratesVersion1Ports) {
    TemporaryDirectory directory;
    const auto scenario_path = (directory.path() / "scenario.yaml").generic_string();
    const auto path = directory.path() / "profile.json";
    write_text(path, R"({
      "version": 1,
      "source": {"type": "video", "path": ")" + (directory.path() / "run.mp4").generic_string() + R"("},
      "instances": [
        {"connection": {"rpc_endpoint": "tcp://127.0.0.1:10000", "event_endpoint": "tcp://127.0.0.1:10001"}, "scenario": ")" + scenario_path + R"("},
        {"connection": {"rpc_endpoint": "tcp://127.0.0.1:10002", "event_endpoint": "tcp://127.0.0.1:10003"}, "scenario": ")" + scenario_path + R"("}
      ]
    })");

    const auto loaded = load_profile(path);
    EXPECT_TRUE(loaded.migrated);
    EXPECT_EQ(loaded.profile.version, 2);
    ASSERT_EQ(loaded.profile.instances.size(), 2U);
    EXPECT_EQ(loaded.profile.instances[0].connection.port, 54000);
    EXPECT_EQ(loaded.profile.instances[1].connection.port, 54001);
}

TEST(Profile, RejectsUnknownFields) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "profile.json";
    write_text(path, R"({
      "version": 2,
      "source": {"type": "video", "path": ")" + (directory.path() / "run.mp4").generic_string() + R"("},
      "instances": [],
      "runtime": {}
    })");
    EXPECT_THROW((void)load_profile(path), ConfigurationError);
}

TEST(Profile, RejectsRelativePaths) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "profile.json";
    write_text(path, R"({
      "version": 2,
      "source": {"type": "video", "path": "run.mp4"},
      "instances": [{"connection": {"port": 54000}, "scenario": "scenario.yaml"}]
    })");
    EXPECT_THROW((void)load_profile(path), ConfigurationError);
}

TEST(Profile, RejectsInvalidPort) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "profile.json";
    write_text(path, R"({
      "version": 2,
      "source": {"type": "video", "path": ")" + (directory.path() / "run.mp4").generic_string() + R"("},
      "instances": [{"connection": {"port": 0}, "scenario": ")" + (directory.path() / "scenario.yaml").generic_string() + R"("}]
    })");
    EXPECT_THROW((void)load_profile(path), ConfigurationError);
}

TEST(AppSettings, RoundTrips) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "settings.json";
    AppSettings settings;
    settings.log_level = "DEBUG";
    settings.reaction_time_ms = 250;
    settings.last_profile = (directory.path() / "profile.json").string();
    settings.theme = "dark";
    save_app_settings(path, settings);
    const auto loaded = load_app_settings(path);
    EXPECT_EQ(loaded.log_level, "DEBUG");
    EXPECT_EQ(loaded.reaction_time_ms, 250);
    ASSERT_TRUE(loaded.last_profile.has_value());
    EXPECT_EQ(*loaded.last_profile, *settings.last_profile);
    EXPECT_EQ(loaded.theme, "dark");
}

TEST(AppSettings, RejectsUnknownField) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "settings.json";
    write_text(path, R"({"version": 1, "log_level": "INFO", "reaction_time_ms": 0, "extra": true})");
    EXPECT_THROW(load_app_settings(path), ConfigurationError);
}
