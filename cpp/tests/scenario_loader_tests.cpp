#include <gtest/gtest.h>

#include <opencv2/imgcodecs.hpp>

#include <filesystem>
#include <fstream>
#include <string>

#include "divergencesplitter/scenario/scenario.hpp"

using namespace divergencesplitter;

namespace {

class TemporaryDirectory {
public:
    TemporaryDirectory() {
        static int counter = 0;
        path_ = std::filesystem::temp_directory_path() /
                ("divergencesplitter-yaml-" + std::to_string(++counter) + "-" +
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

std::filesystem::path write_reference(const std::filesystem::path& directory) {
    cv::Mat image(8, 8, CV_8UC3);
    for (int row = 0; row < image.rows; ++row) {
        for (int column = 0; column < image.cols; ++column) {
            image.at<cv::Vec3b>(row, column) = cv::Vec3b{
                static_cast<unsigned char>(row * 20),
                static_cast<unsigned char>(column * 20),
                static_cast<unsigned char>((row + column) * 10),
            };
        }
    }
    const auto path = directory / "reference.png";
    EXPECT_TRUE(cv::imwrite(path.string(), image));
    return path;
}

}  // namespace

TEST(ScenarioLoader, LoadsNestedScenario) {
    TemporaryDirectory directory;
    write_reference(directory.path());
    const auto scenario_path = directory.path() / "scenario.yaml";
    write_text(scenario_path, R"(
start_condition:
  type: detected
  minimum_score: 0.5
  detector:
    type: mean_brightness
reset_condition:
  type: not
  condition:
    type: detected
    minimum_score: 0.9
    detector:
      type: mean_brightness
incomplete_condition:
  type: once
  condition:
    type: detected
    minimum_score: 0.5
    detector:
      type: mean_brightness
splits:
  - rules:
      - condition:
          type: all
          conditions:
            - type: elapsed
              duration: 100ms
            - type: not
              condition:
                type: detected
                minimum_score: 0.9
                detector:
                  type: template_match
                  reference: reference.png
        action: split
      - sequence:
          - condition:
              type: detected
              minimum_score: 0.5
              detector:
                type: mean_brightness
            action: skip
          - condition:
              type: falling_edge
              condition:
                type: detected
                minimum_score: 0.5
                detector:
                  type: mean_brightness
            action: undo
  - null
)");

    const auto loaded = load_scenario(scenario_path);
    EXPECT_EQ(loaded.path, scenario_path);
    ASSERT_EQ(loaded.scenario.splits.size(), 2U);
    ASSERT_TRUE(loaded.scenario.reset_condition);
    ASSERT_TRUE(loaded.scenario.incomplete_condition);
    ASSERT_TRUE(loaded.scenario.splits[0].has_value());
    ASSERT_EQ(loaded.scenario.splits[0]->size(), 2U);
    EXPECT_FALSE(loaded.scenario.splits[1].has_value());
    EXPECT_EQ(loaded.scenario.splits[0]->at(0)->type_name(), "rule");
    EXPECT_EQ(loaded.scenario.splits[0]->at(1)->type_name(), "sequence");
}

TEST(ScenarioLoader, RejectsPythonScenario) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.py";
    write_text(path, "scenario = None\n");
    try {
        (void)load_scenario(path);
        FAIL() << "expected ScenarioLoadError";
    } catch (const ScenarioLoadError& error) {
        EXPECT_EQ(error.kind(), ScenarioErrorKind::unsupported_python);
    }
}

TEST(ScenarioLoader, RejectsUnknownDetector) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
start_condition:
  type: detected
  minimum_score: 0.5
  detector:
    type: unknown_detector
splits: []
)");
    try {
        (void)load_scenario(path);
        FAIL() << "expected ScenarioLoadError";
    } catch (const ScenarioLoadError& error) {
        EXPECT_EQ(error.kind(), ScenarioErrorKind::schema);
    }
}

TEST(ScenarioLoader, RejectsUnknownField) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
start_condition:
  type: detected
  minimum_score: 0.5
  detector:
    type: mean_brightness
    mystery: 1
splits: []
)");
    EXPECT_THROW((void)load_scenario(path), ScenarioLoadError);
}

TEST(ScenarioLoader, RejectsInvalidDuration) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
start_condition:
  type: elapsed
  duration: 5 minutes
splits: []
)");
    EXPECT_THROW((void)load_scenario(path), ScenarioLoadError);
}

TEST(ScenarioLoader, RejectsMissingReferenceImage) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
start_condition:
  type: detected
  minimum_score: 0.5
  detector:
    type: template_match
    reference: missing.png
splits: []
)");
    EXPECT_THROW((void)load_scenario(path), ScenarioLoadError);
}

TEST(ScenarioLoader, ParsesThenWithinAndRoi) {
    TemporaryDirectory directory;
    write_reference(directory.path());
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
start_condition:
  type: then
  within: 2s
  conditions:
    - type: detected
      minimum_score: 0.5
      detector:
        type: template_match
        reference: reference.png
        roi:
          x: 1
          y: 2
          width: 4
          height: 3
    - type: elapsed
      duration: 500ms
splits:
  - null
)");
    const auto loaded = load_scenario(path);
    ASSERT_TRUE(loaded.scenario.start_condition);
    EXPECT_EQ(loaded.scenario.start_condition->type_name(), "then");
    const auto reference_images = loaded.scenario.start_condition->children().front()->detector();
    ASSERT_NE(reference_images, nullptr);
    EXPECT_EQ(reference_images->type_name(), "template_match");
}
