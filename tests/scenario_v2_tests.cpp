#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detector.hpp"
#include "divergencesplitter/scenario/scenario.hpp"

using namespace divergencesplitter;

namespace {

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
    const auto* start = dynamic_cast<const DetectedCondition*>(
        loaded.scenario.start_condition.get()
    );
    ASSERT_NE(start, nullptr);
    EXPECT_DOUBLE_EQ(start->minimum_score(), 0.75);
    ASSERT_NE(start->detector(), nullptr);
    EXPECT_EQ(start->detector()->type_name(), "color_range");
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
    const auto* start = dynamic_cast<const ElapsedCondition*>(
        loaded.scenario.start_condition.get()
    );
    ASSERT_NE(start, nullptr);
    EXPECT_EQ(start->duration(), std::chrono::seconds{1});
}

TEST(ScenarioV2, UsesIndependentConditionInstancesPerUsage) {
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
    ASSERT_TRUE(loaded.scenario.splits[0].has_value());
    const auto* start = dynamic_cast<const ElapsedCondition*>(
        loaded.scenario.start_condition.get()
    );
    const auto* rule = dynamic_cast<const ElapsedCondition*>(
        loaded.scenario.splits[0]->at(0)->active_condition()
    );
    ASSERT_NE(start, nullptr);
    ASSERT_NE(rule, nullptr);
    EXPECT_NE(start, rule);
    EXPECT_EQ(rule->duration(), std::chrono::seconds{2});
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
    const auto* start = dynamic_cast<const DetectedCondition*>(
        loaded.scenario.start_condition.get()
    );
    ASSERT_NE(start, nullptr);
    EXPECT_EQ(start->detector()->type_name(), "color_range");
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
    const auto* start = dynamic_cast<const ElapsedCondition*>(
        loaded.scenario.start_condition.get()
    );
    ASSERT_NE(start, nullptr);
    EXPECT_EQ(start->duration(), std::chrono::seconds{1});
}

namespace {

std::string describe_tree(const Condition* condition) {
    if (condition == nullptr) {
        return "<null>";
    }
    std::string result{condition->type_name()};
    const auto children = condition->children();
    if (!children.empty()) {
        result += "(";
        for (std::size_t index = 0; index < children.size(); ++index) {
            if (index != 0) {
                result += ",";
            }
            result += describe_tree(children[index]);
        }
        result += ")";
    }
    return result;
}

}  // namespace

TEST(ScenarioV2, LegacyAndV2ResolveToTheSameConditionTree) {
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
    const auto legacy_loaded = load_scenario(legacy);
    const auto v2_loaded = load_scenario(v2);
    EXPECT_EQ(
        describe_tree(legacy_loaded.scenario.start_condition.get()),
        describe_tree(v2_loaded.scenario.start_condition.get())
    );
    ASSERT_EQ(v2_loaded.scenario.splits.size(), 1U);
    ASSERT_TRUE(v2_loaded.scenario.splits[0].has_value());
    EXPECT_EQ(
        describe_tree(legacy_loaded.scenario.splits[0]->at(0)->active_condition()),
        describe_tree(v2_loaded.scenario.splits[0]->at(0)->active_condition())
    );
}

TEST(ScenarioV2, AcceptsUtf8Bom) {
    TemporaryDirectory directory;
    const auto path = write_scenario(directory, "\xEF\xBB\xBFschema_version: 2\nstart_condition: {type: elapsed, duration: 1s}\nsplits: []\n");
    const auto loaded = load_scenario(path);
    const auto* start = dynamic_cast<const ElapsedCondition*>(
        loaded.scenario.start_condition.get()
    );
    ASSERT_NE(start, nullptr);
    EXPECT_EQ(start->duration(), std::chrono::seconds{1});
}

TEST(ScenarioV2, OmitsOptionalFieldsWithNullParameterDefaults) {
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
          - type: elapsed
            duration: 1s
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
    const auto* start = dynamic_cast<const ThenCondition*>(
        loaded.scenario.start_condition.get()
    );
    ASSERT_NE(start, nullptr);
    EXPECT_NE(start->describe().find("within 3s"), std::string::npos);
    ASSERT_EQ(loaded.scenario.splits.size(), 1U);
    const auto* rule = dynamic_cast<const ThenCondition*>(
        loaded.scenario.splits[0]->at(0)->active_condition()
    );
    ASSERT_NE(rule, nullptr);
    EXPECT_EQ(rule->describe().find("within"), std::string::npos);
}
