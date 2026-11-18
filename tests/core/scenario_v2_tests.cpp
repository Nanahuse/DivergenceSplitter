#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>

#include "divergencesplitter/scenario/scenario.hpp"

using namespace divergencesplitter;

namespace {

using namespace std::chrono_literals;

FrameContext frame_at(std::chrono::nanoseconds time, const cv::Mat& image) {
    const MonotonicTime timestamp{time.count()};
    return FrameContext{Frame{image, timestamp}, timestamp};
}

void expect_elapsed(const ConditionPtr& condition, std::chrono::nanoseconds duration) {
    ASSERT_TRUE(condition);
    const cv::Mat image(1, 1, CV_8UC3, cv::Scalar::all(0));
    auto first = frame_at(0s, image);
    auto before = frame_at(duration - 1ms, image);
    auto at = frame_at(duration, image);
    EXPECT_EQ(condition->evaluate(first), false);
    EXPECT_EQ(condition->evaluate(before), false);
    EXPECT_EQ(condition->evaluate(at), true);
}

class TemporaryDirectory {
public:
    TemporaryDirectory() {
        static int counter = 0;
        path_ = std::filesystem::temp_directory_path()
            / ("divergencesplitter-v2-" + std::to_string(++counter) + "-"
               + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
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

std::filesystem::path write_scenario(
    TemporaryDirectory& directory,
    std::string_view text
) {
    const auto path = directory.path() / "scenario.yaml";
    std::ofstream stream{path, std::ios::binary};
    stream << text;
    return path;
}

void expect_load_error(const std::filesystem::path& path, std::string_view expected) {
    try {
        (void)load_scenario(path);
        FAIL() << "expected ScenarioLoadError";
    } catch (const ScenarioLoadError& error) {
        EXPECT_NE(std::string_view{error.what()}.find(expected), std::string_view::npos)
            << error.what();
    }
}

}  // namespace

TEST(ScenarioV2, ResolvesDefaultsWithAndNestedDefinitions) {
    TemporaryDirectory directory;
    const auto path = write_scenario(directory, R"(
schema_version: 2

definitions:
  detectors:
    green:
      parameters:
        lower: [0, 100, 0]
        upper: [100, 255, 100]
      detector:
        type: color_range
        lower: {param: lower}
        upper: {param: upper}
  conditions:
    finish:
      parameters:
        score: 0.9
        lower: [0, 120, 0]
      condition:
        type: detected
        minimum_score: {param: score}
        detector:
          use: green
          with:
            lower: {param: lower}

start_condition:
  use: finish
  with:
    score: 0.75
    lower: [0, 140, 0]
splits: []
)");
    const auto loaded = load_scenario(path);
    ASSERT_TRUE(loaded.scenario.start_condition);
    cv::Mat image(1, 4, CV_8UC3, cv::Scalar{0, 140, 0});
    image.at<cv::Vec3b>(0, 0) = {101, 140, 0};
    auto at_minimum = frame_at(0s, image);
    EXPECT_EQ(loaded.scenario.start_condition->evaluate(at_minimum), true);

    cv::Mat below = image.clone();
    below.at<cv::Vec3b>(0, 1) = {0, 139, 0};
    auto below_minimum = frame_at(1ms, below);
    EXPECT_EQ(loaded.scenario.start_condition->evaluate(below_minimum), false);
}

TEST(ScenarioV2, DefinitionOrderDoesNotMatter) {
    TemporaryDirectory directory;
    const auto path = write_scenario(directory, R"(
schema_version: 2
definitions:
  conditions:
    outer:
      condition:
        use: inner
    inner:
      parameters:
        duration: 1s
      condition:
        type: elapsed
        duration: {param: duration}
start_condition:
  use: outer
splits: []
)");
    const auto loaded = load_scenario(path);
    expect_elapsed(loaded.scenario.start_condition, 1s);
}

TEST(ScenarioV2, ASharedSplitConditionStartsItsOwnTimer) {
    TemporaryDirectory directory;
    const auto path = write_scenario(directory, R"(
schema_version: 2
definitions:
  conditions:
    wait:
      condition:
        type: elapsed
        duration: 2s
start_condition:
  use: wait
splits:
  - rules:
      - condition:
          use: wait
        action: split
)");
    const auto loaded = load_scenario(path);
    ASSERT_TRUE(loaded.scenario.start_condition);
    ASSERT_EQ(loaded.scenario.splits.size(), 1U);
    ASSERT_TRUE(loaded.scenario.splits[0]);
    ASSERT_EQ(loaded.scenario.splits[0]->size(), 1U);
    const auto& rule = loaded.scenario.splits[0]->at(0);
    const cv::Mat image(1, 1, CV_8UC3, cv::Scalar::all(0));
    auto first = frame_at(0s, image);
    auto second = frame_at(2s, image);
    auto third = frame_at(4s, image);
    EXPECT_EQ(loaded.scenario.start_condition->evaluate(first), false);
    EXPECT_EQ(loaded.scenario.start_condition->evaluate(second), true);
    EXPECT_EQ(rule->evaluate(second), std::nullopt);
    EXPECT_EQ(rule->evaluate(third), (Action{ActionOperation::split}));
}

TEST(ScenarioV2, RejectsUnknownDefinitionsParametersAndTypeMismatches) {
    TemporaryDirectory directory;
    expect_load_error(
        write_scenario(directory, R"(
schema_version: 2
start_condition: {use: missing}
splits: []
)"),
        "definition was not found"
    );
    expect_load_error(
        write_scenario(directory, R"(
schema_version: 2
definitions:
  conditions:
    wait:
      parameters:
        duration: 1s
      condition:
        type: elapsed
        duration: {param: duration}
start_condition:
  use: wait
  with:
    unknown: 2s
splits: []
)"),
        "unknown parameter"
    );
    expect_load_error(
        write_scenario(directory, R"(
schema_version: 2
definitions:
  detectors:
    bright:
      detector:
        type: mean_brightness
start_condition:
  use: bright
splits: []
)"),
        "detector definition"
    );
    expect_load_error(
        write_scenario(directory, R"(
schema_version: 2
definitions:
  conditions:
    wait:
      condition:
        type: detected
        minimum_score: 0.5
        detector:
          use: wait
start_condition:
  use: wait
splits: []
)"),
        "condition definition"
    );
    expect_load_error(
        write_scenario(directory, R"(
schema_version: 2
start_condition:
  type: elapsed
  duration: {param: missing}
splits: []
)"),
        "parameter is not defined"
    );
}

TEST(ScenarioV2, RejectsDefinitionAndParameterCycles) {
    TemporaryDirectory directory;
    expect_load_error(
        write_scenario(directory, R"(
schema_version: 2
definitions:
  conditions:
    first:
      condition:
        use: second
    second:
      condition:
        use: first
start_condition:
  use: first
splits: []
)"),
        "cyclic condition definition"
    );
    expect_load_error(
        write_scenario(directory, R"(
schema_version: 2
definitions:
  conditions:
    wait:
      parameters:
        first: {param: second}
        second: {param: first}
      condition:
        type: elapsed
        duration: {param: first}
start_condition:
  use: wait
splits: []
)"),
        "cyclic parameter reference"
    );
}

TEST(ScenarioV2, ExtendsCanNestDetectorParametersPerUsage) {
    TemporaryDirectory directory;
    const auto path = write_scenario(directory, R"(
schema_version: 2
definitions:
  detectors:
    mixed:
      parameters:
        lower: [0, 100, 0]
      detector:
        type: color_range
        lower: {param: lower}
        upper: [120, 255, 120]
  conditions:
    frame:
      parameters:
        lower: [0, 110, 0]
      condition:
        type: detected
        minimum_score: 0.8
        detector:
          use: mixed
          with:
            lower: {param: lower}
start_condition:
  use: frame
  with:
    lower: [0, 130, 0]
splits: []
)");
    const auto loaded = load_scenario(path);
    ASSERT_TRUE(loaded.scenario.start_condition);
    auto below = frame_at(0s, cv::Mat(1, 1, CV_8UC3, cv::Scalar{0, 129, 0}));
    auto at = frame_at(1ms, cv::Mat(1, 1, CV_8UC3, cv::Scalar{0, 130, 0}));
    EXPECT_EQ(loaded.scenario.start_condition->evaluate(below), false);
    EXPECT_EQ(loaded.scenario.start_condition->evaluate(at), true);
}

TEST(ScenarioV2, LegacyScenariosStillLoad) {
    TemporaryDirectory directory;
    const auto path = write_scenario(directory, R"(
start_condition:
  type: elapsed
  duration: 1s
splits: []
)");
    const auto loaded = load_scenario(path);
    expect_elapsed(loaded.scenario.start_condition, 1s);
}

TEST(ScenarioV2, LegacyAndV2StartAndSplitOnTheSameInputs) {
    TemporaryDirectory legacy_directory;
    const auto legacy = write_scenario(legacy_directory, R"(
start_condition:
  type: detected
  minimum_score: 0.5
  detector:
    type: color_range
    lower: [0, 100, 0]
    upper: [100, 255, 100]
splits:
  - rules:
      - condition:
          type: elapsed
          duration: 5s
        action: split
)");
    TemporaryDirectory v2_directory;
    const auto v2 = write_scenario(v2_directory, R"(
schema_version: 2
definitions:
  conditions:
    main:
      parameters:
        lower: [0, 100, 0]
      condition:
        type: detected
        minimum_score: 0.5
        detector:
          type: color_range
          lower: {param: lower}
          upper: [100, 255, 100]
start_condition:
  use: main
splits:
  - rules:
      - condition:
          type: elapsed
          duration: 5s
        action: split
)");
    for (const auto& path : {legacy, v2}) {
        SCOPED_TRACE(path.string());
        const auto loaded = load_scenario(path);
        ASSERT_TRUE(loaded.scenario.start_condition);
        ASSERT_EQ(loaded.scenario.splits.size(), 1U);
        ASSERT_TRUE(loaded.scenario.splits[0]);
        ASSERT_EQ(loaded.scenario.splits[0]->size(), 1U);
        const auto& rule = loaded.scenario.splits[0]->at(0);
        const cv::Mat green(1, 1, CV_8UC3, cv::Scalar{0, 128, 0});
        const cv::Mat dark(1, 1, CV_8UC3, cv::Scalar::all(0));
        auto before_start = frame_at(0s, dark);
        auto start = frame_at(1s, green);
        auto before_split = frame_at(5999ms, dark);
        auto split = frame_at(6s, dark);
        EXPECT_EQ(loaded.scenario.start_condition->evaluate(before_start), false);
        EXPECT_EQ(loaded.scenario.start_condition->evaluate(start), true);
        EXPECT_EQ(rule->evaluate(start), std::nullopt);
        EXPECT_EQ(rule->evaluate(before_split), std::nullopt);
        EXPECT_EQ(rule->evaluate(split), (Action{ActionOperation::split}));
    }
}

TEST(ScenarioV2, AcceptsUtf8Bom) {
    TemporaryDirectory directory;
    const auto path = write_scenario(directory, "\xEF\xBB\xBFschema_version: 2\nstart_condition: {type: elapsed, duration: 1s}\nsplits: []\n");
    const auto loaded = load_scenario(path);
    expect_elapsed(loaded.scenario.start_condition, 1s);
}

TEST(ScenarioV2, NullTimeLimitAllowsASequenceToCompleteAfterTheOverrideExpires) {
    TemporaryDirectory directory;
    const auto path = write_scenario(directory, R"(
schema_version: 2
definitions:
  conditions:
    sequence:
      parameters:
        within_value: null
      condition:
        type: then
        within: {param: within_value}
        conditions:
          - type: detected
            detector: {type: mean_brightness}
            minimum_score: 0.8
          - type: detected
            detector: {type: mean_brightness}
            minimum_score: 0.3
start_condition:
  use: sequence
  with:
    within_value: 3s
splits:
  - rules:
      - condition:
          use: sequence
        action: split
)");
    const auto loaded = load_scenario(path);
    ASSERT_TRUE(loaded.scenario.start_condition);
    ASSERT_EQ(loaded.scenario.splits.size(), 1U);
    ASSERT_TRUE(loaded.scenario.splits[0]);
    ASSERT_EQ(loaded.scenario.splits[0]->size(), 1U);
    const auto& rule = loaded.scenario.splits[0]->at(0);
    auto bright = frame_at(0s, cv::Mat(1, 1, CV_8UC3, cv::Scalar::all(255)));
    auto dim = frame_at(4s, cv::Mat(1, 1, CV_8UC3, cv::Scalar::all(128)));
    EXPECT_EQ(loaded.scenario.start_condition->evaluate(bright), false);
    EXPECT_EQ(rule->evaluate(bright), std::nullopt);
    EXPECT_EQ(loaded.scenario.start_condition->evaluate(dim), false);
    EXPECT_EQ(rule->evaluate(dim), (Action{ActionOperation::split}));
}
