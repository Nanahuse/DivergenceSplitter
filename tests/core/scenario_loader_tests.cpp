#include <gtest/gtest.h>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <ryml/ryml.hpp>

#include <filesystem>
#include <fstream>
#include <string>

#include "divergencesplitter/scenario/scenario.hpp"
#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
#include "divergencesplitter/runtime/session.hpp"
#include "divergencesplitter/runtime/scenario_runtime.hpp"
#include "test_support.hpp"

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

void expect_load_error(const std::filesystem::path& path, ScenarioErrorKind kind, std::string_view field = {}) {
    try {
        (void)load_scenario(path);
        FAIL() << "expected ScenarioLoadError";
    } catch (const ScenarioLoadError& error) {
        EXPECT_EQ(error.kind(), kind) << error.what();
        EXPECT_NE(std::string_view{error.what()}.find(field), std::string_view::npos) << error.what();
    }
}

}  // namespace

TEST(ScenarioLoader, SharesMatchingRmsDetectorsWithinOneLoad) {
    TemporaryDirectory directory;
    const auto reference = write_reference(directory.path());
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
definitions:
  condition: &condition
    type: detected
    minimum_score: 0.9
    detector: &detector {type: root_mean_square_similarity, reference: reference.png}
start_condition:
  type: all
  conditions:
    - <<: *condition
      minimum_score: 0.25
    - <<: *condition
    - <<: *condition
      detector:
        <<: *detector
        roi: {x: 0, y: 0, width: 8, height: 8}
splits: []
)");

    const auto original = load_scenario(path);
    const auto conditions = original.scenario.start_condition->children();
    ASSERT_EQ(conditions.size(), 3U);
    const auto* first = dynamic_cast<const DetectedCondition*>(conditions[0]);
    const auto* second = dynamic_cast<const DetectedCondition*>(conditions[1]);
    ASSERT_NE(first, nullptr);
    ASSERT_NE(second, nullptr);
    EXPECT_DOUBLE_EQ(first->minimum_score(), 0.25);
    EXPECT_DOUBLE_EQ(second->minimum_score(), 0.9);
    ASSERT_NE(first->detector(), nullptr);
    EXPECT_EQ(first->detector(), second->detector());
    EXPECT_NE(first->detector(), conditions[2]->detector());

    ASSERT_TRUE(cv::imwrite(reference.string(), cv::Mat(8, 8, CV_8UC3, cv::Scalar::all(255))));
    const auto reloaded = load_scenario(path);
    const auto reloaded_conditions = reloaded.scenario.start_condition->children();
    ASSERT_EQ(reloaded_conditions.size(), 3U);
    ASSERT_NE(reloaded_conditions[0]->detector(), nullptr);
    EXPECT_NE(first->detector()->cache_key(), reloaded_conditions[0]->detector()->cache_key());
}

TEST(ScenarioLoader, ResolvesNestedMergesAndExplicitOverrides) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
definitions:
  detected: &detected
    type: detected
    minimum_score: 0.9
    detector: &detector {type: mean_brightness}
  nested: &nested
    <<: *detected
    minimum_score: 0.8
start_condition:
  <<: *nested
  minimum_score: 0.95
reset_condition: *detected
splits:
  - rules:
      - condition:
          <<: *nested
          minimum_score: 0.7
        action: split
)");
    const auto loaded = load_scenario(path);
    const auto check = [](const Condition* condition, double score) {
        const auto* detected = dynamic_cast<const DetectedCondition*>(condition);
        ASSERT_NE(detected, nullptr);
        EXPECT_DOUBLE_EQ(detected->minimum_score(), score);
        ASSERT_NE(detected->detector(), nullptr);
        EXPECT_EQ(detected->detector()->type_name(), "mean_brightness");
    };
    check(loaded.scenario.start_condition.get(), 0.95);
    check(loaded.scenario.reset_condition.get(), 0.9);
    check(loaded.scenario.splits[0]->at(0)->active_condition(), 0.7);
}

TEST(ScenarioLoader, MergePriorityMatchesRapidyamlSourceOrder) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    const std::string definitions = R"(
a: &a {type: detected, minimum_score: 0.2, detector: {type: mean_brightness}}
b: &b {minimum_score: 0.8, detector: {type: mean_brightness}}
combined: &combined {<<: [*a, *b]}
splits: []
start_condition:
)";
    for (const auto& [mapping, score] : std::vector<std::pair<std::string, double>>{
        {"  <<: [*a, *b]\n", 0.8},
        {"  <<: [*b, *a]\n", 0.2},
        {"  <<: *a\n  minimum_score: 0.5\n", 0.5},
        {"  <<: *combined\n  minimum_score: 0.95\n", 0.95},
        {"  minimum_score: 0.5\n  <<: *a\n", 0.2},
        {"  <<: [*a, *b]\n  minimum_score: 0.5\n", 0.8},
        {"  minimum_score: 0.5\n  <<: [*a, *b]\n", 0.8},
    }) {
        SCOPED_TRACE(mapping);
        write_text(path, definitions + mapping);
        const auto loaded = load_scenario(path);
        const auto* detected = dynamic_cast<const DetectedCondition*>(loaded.scenario.start_condition.get());
        ASSERT_NE(detected, nullptr);
        EXPECT_DOUBLE_EQ(detected->minimum_score(), score);
    }
}

TEST(ScenarioLoader, AliasesAndMergesBuildIndependentConditionState) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
definitions:
  once: &once {type: once, condition: {type: elapsed, duration: 1s}}
start_condition: *once
reset_condition: {<<: *once}
splits:
  - rules:
      - {condition: *once, action: split}
)");
    const auto loaded = load_scenario(path);
    auto& start = loaded.scenario.start_condition;
    auto& reset = loaded.scenario.reset_condition;
    EXPECT_NE(start.get(), reset.get());
    EXPECT_NE(start->children()[0], reset->children()[0]);
    test::ManualTimeProvider clock;
    auto context = test::make_context(cv::Mat::zeros(2, 2, CV_8UC3), clock);
    EXPECT_EQ(start->evaluate(context), false);
    clock.advance(std::chrono::seconds{1});
    context = test::make_context(cv::Mat::zeros(2, 2, CV_8UC3), clock);
    EXPECT_EQ(start->evaluate(context), true);
    EXPECT_EQ(reset->evaluate(context), false);
    clock.advance(std::chrono::seconds{1});
    context = test::make_context(cv::Mat::zeros(2, 2, CV_8UC3), clock);
    EXPECT_EQ(reset->evaluate(context), true);
    EXPECT_EQ(loaded.scenario.splits[0]->at(0)->active_condition()->type_name(), "once");
}

TEST(ScenarioLoader, InvalidYamlAndReferencesThrowWithoutChangingGlobalCallbacks) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    const auto callbacks = ryml::get_callbacks();
    for (const auto* source : {
        "start_condition: [broken\n",
        "start_condition: *missing\nsplits: []\n",
        "a: &a {type: not, condition: *a}\nstart_condition: *a\nsplits: []\n",
        "a: &a [*a]\nstart_condition: *a\nsplits: []\n",
        "a: &a {nested: &b {nested: *a}}\nstart_condition: *b\nsplits: []\n",
        "a: &a {<<: *a}\nstart_condition: *a\nsplits: []\n",
        "a: &a {extends: *a}\nstart_condition: *a\nsplits: []\n",
        "start_condition: {extends: *missing}\nsplits: []\n",
        "a: &a scalar\nstart_condition: {<<: *a}\nsplits: []\n",
        "a: &a [1, 2]\nstart_condition: {<<: [*a]}\nsplits: []\n",
        "start_condition: {<<: [not_an_alias]}\nsplits: []\n",
        "start_condition: {<<: [{type: elapsed}]}\nsplits: []\n",
    }) {
        SCOPED_TRACE(source);
        write_text(path, source);
        expect_load_error(path, ScenarioErrorKind::yaml);
        EXPECT_EQ(ryml::get_callbacks(), callbacks);
        write_text(path, "start_condition: {type: elapsed, duration: 0s}\nsplits: []\n");
        EXPECT_NO_THROW((void)load_scenario(path));
    }
}

TEST(ScenarioLoader, InheritanceBuildsIndependentThenStateEquivalentToDirectYaml) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
definitions:
  base: &base
    type: then
    conditions:
      - {type: elapsed, duration: 0s}
      - {id: pause, type: elapsed, duration: 2s}
start_condition:
  type: then
  conditions:
    - {type: elapsed, duration: 0s}
    - {type: elapsed, duration: 1s}
splits:
  - rules:
      - condition: {extends: *base, overrides: {pause: {duration: 1s}}}
        action: split
  - rules:
      - condition: {extends: *base}
        action: split
)");
    const auto loaded = load_scenario(path);
    auto& direct = *loaded.scenario.start_condition;
    auto& first = *std::dynamic_pointer_cast<Rule>(loaded.scenario.splits[0]->at(0))->condition();
    auto& second = *std::dynamic_pointer_cast<Rule>(loaded.scenario.splits[1]->at(0))->condition();
    EXPECT_NE(first.children()[1], second.children()[1]);
    test::ManualTimeProvider clock;
    const auto frame = cv::Mat::zeros(2, 2, CV_8UC3);
    const auto evaluate = [&](Condition& condition) {
        auto context = test::make_context(frame, clock);
        return condition.evaluate(context);
    };
    EXPECT_EQ(evaluate(direct), false);
    EXPECT_EQ(evaluate(first), false);
    EXPECT_EQ(evaluate(direct), false);
    EXPECT_EQ(evaluate(first), false);
    clock.advance(std::chrono::seconds{1});
    EXPECT_EQ(evaluate(direct), true);
    EXPECT_EQ(evaluate(first), true);
    EXPECT_EQ(evaluate(second), false);
    EXPECT_EQ(evaluate(second), false);
    clock.advance(std::chrono::seconds{1});
    EXPECT_EQ(evaluate(second), false);
    clock.advance(std::chrono::seconds{1});
    EXPECT_EQ(evaluate(second), true);
}

TEST(ScenarioLoader, InheritanceMergesNestedDetectorSettingsAcrossLayers) {
    TemporaryDirectory directory;
    const auto reference = write_reference(directory.path());
    const cv::Mat alternate(8, 8, CV_8UC3, cv::Scalar{40, 80, 120});
    ASSERT_TRUE(cv::imwrite((directory.path() / "alternate.png").string(), alternate));
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
definitions:
  detector: &detector {type: root_mean_square_similarity, reference: reference.png}
  course: &course
    id: course
    type: detected
    minimum_score: 0.9
    detector:
      <<: *detector
      roi: {x: 0, y: 0, width: 8, height: 8}
  base: &base
    id: sequence
    type: then
    within: 2s
    conditions:
      - type: reset_when
        condition: {type: elapsed, duration: 1s}
        reset_condition: {extends: *course}
  mid: &mid
    extends: *base
    overrides:
      course:
        minimum_score: 0.6
        detector: {reference: alternate.png, roi: {x: 1}}
start_condition:
  extends: *mid
  overrides:
    course:
      minimum_score: 0.7
      detector: {roi: {y: 2}}
reset_condition:
  extends: *mid
  overrides:
    sequence: {within: null}
    course: {detector: {roi: null}}
incomplete_condition: *base
splits: []
)");
    const auto loaded = load_scenario(path);
    const auto nested = [](const Condition& condition) {
        return dynamic_cast<const DetectedCondition*>(condition.children().at(0)->children().at(1));
    };
    const auto* start = nested(*loaded.scenario.start_condition);
    const auto* reset = nested(*loaded.scenario.reset_condition);
    const auto* base = nested(*loaded.scenario.incomplete_condition);
    ASSERT_NE(start, nullptr);
    ASSERT_NE(reset, nullptr);
    ASSERT_NE(base, nullptr);
    EXPECT_DOUBLE_EQ(start->minimum_score(), 0.7);
    EXPECT_DOUBLE_EQ(reset->minimum_score(), 0.6);
    EXPECT_DOUBLE_EQ(base->minimum_score(), 0.9);
    EXPECT_EQ(start->detector()->type_name(), "root_mean_square_similarity");
    const RootMeanSquareSimilarityDetector expected_start{alternate, Region{1, 2, 8, 8}};
    const RootMeanSquareSimilarityDetector expected_reset{alternate};
    EXPECT_EQ(start->detector()->cache_key(), expected_start.cache_key());
    EXPECT_EQ(reset->detector()->cache_key(), expected_reset.cache_key());
    EXPECT_NE(loaded.scenario.start_condition->describe().find("within"), std::string::npos);
    EXPECT_EQ(loaded.scenario.reset_condition->describe().find("within"), std::string::npos);
    test::ManualTimeProvider clock;
    auto alternate_context = test::make_context(alternate, clock);
    EXPECT_DOUBLE_EQ(reset->detector()->detect(alternate_context).score, 1.0);
    auto original_context = test::make_context(cv::imread(reference.string()), clock);
    EXPECT_DOUBLE_EQ(base->detector()->detect(original_context).score, 1.0);
}

TEST(ScenarioLoader, InheritanceReplacesSequencesAndWorksInRuleSequences) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
definitions:
  base: &base
    id: color
    type: detected
    minimum_score: 0.9
    detector: {type: color_range, lower: [0, 0, 0], upper: [255, 255, 255]}
  patch: &patch {id: shade, extends: *base, overrides: {color: {detector: {lower: [20], upper: [30]}}}}
  merged: &merged {<<: *patch}
start_condition: {type: elapsed, duration: 0s}
splits:
  - rules:
      - sequence:
          - condition: {extends: *merged, overrides: {shade: {minimum_score: 1.0}}}
            action: split
)");
    const auto loaded = load_scenario(path);
    const auto* condition = loaded.scenario.splits[0]->at(0)->active_condition();
    test::ManualTimeProvider clock;
    auto inside = test::make_context(cv::Mat(2, 2, CV_8UC1, cv::Scalar{25}), clock);
    auto outside = test::make_context(cv::Mat(2, 2, CV_8UC1, cv::Scalar{10}), clock);
    EXPECT_DOUBLE_EQ(condition->detector()->detect(inside).score, 1.0);
    EXPECT_DOUBLE_EQ(condition->detector()->detect(outside).score, 0.0);
}

TEST(ScenarioLoader, RejectsInvalidInheritanceWithSettingPaths) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    const std::string definitions = R"(
scalar: &scalar text
list: &list [1, 2]
mapping: &mapping {id: course}
detector: &detector {type: mean_brightness}
base: &base
  id: course
  type: detected
  minimum_score: 0.9
  detector: {type: root_mean_square_similarity, reference: original.png, roi: {x: 0, y: 0, width: 8, height: 8}}
bad_reference: &bad_reference
  extends: *base
  overrides: {course: {detector: {reference: missing.png}}}
bad_roi: &bad_roi
  extends: *base
  overrides: {course: {detector: {roi: {depth: 4}}}}
duplicate: &duplicate
  type: then
  conditions:
    - {type: elapsed, id: course, duration: 1s}
    - {type: elapsed, id: course, duration: 2s}
start_condition: {type: elapsed, duration: 0s}
splits:
  - rules:
      - action: split
        condition: )";
    for (const auto& [mapping, field] : std::vector<std::pair<std::string_view, std::string_view>>{
        {"{extends: base}", ".extends"},
        {"{extends: '*base'}", ".extends"},
        {"{extends: {type: elapsed, duration: 1s}}", ".extends"},
        {"{extends: *scalar}", ".extends"},
        {"{extends: *list}", ".extends"},
        {"{extends: *mapping}", ".extends"},
        {"{extends: *detector}", ".type"},
        {"{type: elapsed, duration: 0s, overrides: {}}", ".overrides"},
        {"{extends: *base, type: elapsed}", ".type"},
        {"{extends: *base, id: null}", ".id"},
        {"{extends: *base, overrides: null}", ".overrides"},
        {"{extends: *base, overrides: {missing: {}}}", ".overrides.missing"},
        {"{extends: *base, overrides: {course: []}}", ".overrides.course"},
        {"{extends: *duplicate, overrides: {course: {duration: 1s}}}", ".overrides.course"},
        {"{extends: *base, overrides: {course: {type: elapsed}}}", ".overrides.course.type"},
        {"{extends: *base, overrides: {course: {id: other}}}", ".overrides.course.id"},
        {"{extends: *base, overrides: {course: {conditions: []}}}", ".overrides.course.conditions"},
        {"{extends: *base, overrides: {course: {condition: {}}}}", ".overrides.course.condition"},
        {"{extends: *base, overrides: {course: {reset_condition: null}}}", ".overrides.course.reset_condition"},
        {"{extends: *base, overrides: {course: {mystery: 1}}}", ".overrides.course.mystery"},
        {"{extends: *base, overrides: {course: {minimum_score: bad}}}", ".overrides.course.minimum_score"},
        {"{extends: *base, overrides: {course: {detector: {type: mean_brightness}}}}", ".overrides.course.detector.type"},
        {"{extends: *base, overrides: {course: {detector: {reference: null}}}}", ".overrides.course.detector.reference"},
        {"{extends: *base, overrides: {course: {detector: {reference: missing.png}}}}", ".overrides.course.detector.reference"},
        {"{extends: *bad_reference, overrides: {course: {detector: {roi: null}}}}", ".extends.overrides.course.detector.reference"},
        {"{extends: *bad_roi, overrides: {course: {detector: {roi: null}}}}", ".extends.overrides.course.detector.roi.depth"},
        {"{extends: *base, overrides: {course: {detector: {roi: {width: 0}}}}}", ".overrides.course.detector.roi"},
    }) {
        SCOPED_TRACE(mapping);
        write_text(path, definitions + std::string(mapping) + "\n");
        expect_load_error(path, ScenarioErrorKind::schema, "splits[0].rules[0].condition" + std::string(field));
    }
}

TEST(ScenarioLoader, RejectsInvalidSchemaAfterMerging) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    for (const auto* mapping : {
        "{type: elapsed, duration: 1s, mystery: 1}",
        "{type: detected, minimum_score: 0.5}",
        "{type: elapsed, duration: null}",
        "{type: elapsed, duration: 1s, duration: 2s}",
    }) {
        SCOPED_TRACE(mapping);
        write_text(path, std::string{"base: &base "} + mapping
            + "\nstart_condition: {<<: *base}\nsplits: []\n");
        expect_load_error(path, ScenarioErrorKind::schema);
    }
}

TEST(ScenarioLoader, PreservesNullAndQuotedStringDistinctions) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    const std::string prefix = "start_condition: {type: elapsed, duration: 0s}\nsplits: [null, ~, ]\n";
    for (const auto* value : {"null", "Null", "NULL", "~", "", "!!null null"}) {
        SCOPED_TRACE(value);
        write_text(path, prefix + "reset_condition: " + value + "\nincomplete_condition: " + value + "\n");
        const auto loaded = load_scenario(path);
        EXPECT_FALSE(loaded.scenario.reset_condition);
        EXPECT_FALSE(loaded.scenario.incomplete_condition);
        EXPECT_EQ(loaded.scenario.splits.size(), 2U);
    }
    for (const auto* value : {"\"null\"", "'~'", "\"\"", "!!str null", "{}", "[]"}) {
        SCOPED_TRACE(value);
        write_text(path, prefix + "reset_condition: " + value + "\n");
        expect_load_error(path, ScenarioErrorKind::schema);
    }
    write_text(path, prefix);
    EXPECT_NO_THROW((void)load_scenario(path));
}

TEST(ScenarioLoader, RejectsInvalidNumericAndDurationScalars) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    for (const auto* value : {"null", "~", "''", "true", "0.5garbage", "1e999", ".nan", ".inf", "[1]"}) {
        SCOPED_TRACE(value);
        write_text(path, std::string{"start_condition: {type: detected, detector: {type: mean_brightness}, minimum_score: "}
            + value + "}\nsplits: []\n");
        expect_load_error(path, ScenarioErrorKind::schema);
    }
    for (const auto* value : {"2147483648", "-2147483649", "1.5", "2x", "null", "[]"}) {
        SCOPED_TRACE(value);
        write_text(path, std::string{"start_condition: {type: nth, condition: {type: elapsed, duration: 0s}, count: "}
            + value + "}\nsplits: []\n");
        expect_load_error(path, ScenarioErrorKind::schema);
    }
    for (const auto* value : {"null", "''", "1", "-1s", "1e3s", "9223372037s", "99999999999999999999999999999999999999999999999999999999s"}) {
        SCOPED_TRACE(value);
        write_text(path, std::string{"start_condition: {type: elapsed, duration: "} + value + "}\nsplits: []\n");
        expect_load_error(path, ScenarioErrorKind::schema);
    }
}

TEST(ScenarioLoader, AcceptsExistingNumericFormatsAndFoldedStrings) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.YML";
    for (const auto* count : {"+2", "02", "0x2", "'2 '"}) {
        SCOPED_TRACE(count);
        write_text(path, std::string{"start_condition:\n  type: nth\n  count: "} + count
            + "\n  condition:\n    type: elapsed\n    duration: >-\n      0.5s\nsplits: []\n");
        EXPECT_NO_THROW((void)load_scenario(path));
    }
}

TEST(ScenarioLoader, RejectsMissingFieldsAndDuplicateKeys) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    for (const auto* source : {
        "", "null", "[]", "splits: []", "start_condition: {type: elapsed, duration: 0s}",
        "start_condition: {duration: 0s}\nsplits: []",
        "start_condition: {type: elapsed, type: elapsed, duration: 0s}\nsplits: []",
        "start_condition: {type: elapsed, duration: 0s}\nsplits: []\nsplits: []",
    }) {
        SCOPED_TRACE(source);
        write_text(path, source);
        expect_load_error(path, ScenarioErrorKind::schema);
    }
    expect_load_error(directory.path() / "missing.yaml", ScenarioErrorKind::io);
}

TEST(ScenarioLoader, PreservesUtf8AndQuotedReferencePaths) {
    TemporaryDirectory directory;
    std::filesystem::create_directory(directory.path() / "images");
    const auto image_path = directory.path() / "images" / std::filesystem::u8path("参照画像.png");
    std::vector<unsigned char> bytes;
    ASSERT_TRUE(cv::imencode(".png", cv::Mat(8, 8, CV_8UC3, cv::Scalar{40, 80, 120}), bytes));
    {
        std::ofstream image{image_path, std::ios::binary};
        image.write(reinterpret_cast<const char*>(bytes.data()), static_cast<std::streamsize>(bytes.size()));
    }
    const auto path = directory.path() / "scenario.yaml";
    for (const auto* reference : {
        "'images/参照画像.png'",
#ifdef _WIN32
        "'images\\参照画像.png'",
#endif
    }) {
        SCOPED_TRACE(reference);
        write_text(path, std::string{"# UTF-8のコメント\nstart_condition:\n  type: detected\n  minimum_score: 0.5\n"
            "  detector:\n    type: mean_absolute_similarity\n    reference: "} + reference + "\nsplits: []\n");
        const auto loaded = load_scenario(path);
        const auto image = loaded.scenario.start_condition->detector()->reference_images()[0].image;
        EXPECT_EQ(image.size(), cv::Size(8, 8));
        EXPECT_EQ(image.at<cv::Vec3b>(0, 0), cv::Vec3b(40, 80, 120));
    }
}

TEST(ScenarioLoader, LoadsFirstDocumentWithAnchorsAndAllowsAnchorRedefinition) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
---
first: &condition {type: elapsed, duration: 0s}
start_condition: *condition
second: &condition {type: once, condition: {type: elapsed, duration: 0s}}
reset_condition: *condition
splits: []
---
ignored: &condition {type: unknown}
)");
    const auto loaded = load_scenario(path);
    EXPECT_EQ(loaded.scenario.start_condition->type_name(), "elapsed");
    EXPECT_EQ(loaded.scenario.reset_condition->type_name(), "once");
}

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

namespace {

std::string reference_scenario(const std::string& type, bool roi = false) {
    return "start_condition:\n"
           "  type: detected\n"
           "  minimum_score: 0.99\n"
           "  detector:\n"
           "    type: " + type + "\n"
           "    reference: reference.png\n" +
           (roi ? "    roi: {x: 3, y: 2, width: 6, height: 4}\n" : "") +
           "splits: []\n";
}

}  // namespace

TEST(ScenarioLoader, ProfileReferenceResizeIsOptInAndNeverCrops) {
    TemporaryDirectory directory;
    const auto image_path = write_reference(directory.path());
    const auto original = cv::imread(image_path.string(), cv::IMREAD_UNCHANGED);
    const auto path = directory.path() / "scenario.yaml";
    for (const bool roi : {false, true}) {
        write_text(path, reference_scenario("mean_absolute_similarity", roi));
        for (const int mode : {0, 1, 2}) {
            TransformConfiguration transform;
            // These margins cannot fit in the reference; they must be ignored.
            transform.crop = CropConfiguration{100, 100, 100, 100};
            if (mode != 0) {
                transform.resize = ResizeConfiguration{12, 10, ResizeInterpolation::linear, mode == 2};
            }
            const auto loaded = load_profile_scenario(path, VideoSourceConfiguration{"", transform});
            const auto image = loaded.scenario.start_condition->detector()->reference_images()[0].image;
            const cv::Size expected_size = mode == 2
                ? (roi ? cv::Size{6, 4} : cv::Size{12, 10}) : original.size();
            EXPECT_EQ(image.size(), expected_size);
            cv::Mat expected;
            cv::resize(original, expected, expected_size, 0.0, 0.0, cv::INTER_LINEAR);
            EXPECT_EQ(cv::norm(image, expected, cv::NORM_INF), 0.0);
        }
    }
    // Loading transforms in memory, leaving both files intact.
    const auto disk_image = cv::imread(image_path.string(), cv::IMREAD_UNCHANGED);
    EXPECT_EQ(cv::norm(disk_image, original, cv::NORM_INF), 0.0);
    std::ifstream stream{path, std::ios::binary};
    const std::string disk_yaml{std::istreambuf_iterator<char>{stream}, {}};
    EXPECT_EQ(disk_yaml, reference_scenario("mean_absolute_similarity", true));
}

TEST(ScenarioLoader, ResizesEveryReferenceDetectorAndPreservesRoiCoordinates) {
    TemporaryDirectory directory;
    // A non-separable texture gives phase correlation a unique peak as well.
    cv::Mat original(8, 8, CV_8UC3);
    cv::RNG random{1234};
    random.fill(original, cv::RNG::UNIFORM, 0, 256);
    ASSERT_TRUE(cv::imwrite((directory.path() / "reference.png").string(), original));
    const auto path = directory.path() / "scenario.yaml";
    const std::pair<ResizeInterpolation, int> interpolations[] = {
        {ResizeInterpolation::area, cv::INTER_AREA},
        {ResizeInterpolation::nearest, cv::INTER_NEAREST},
        {ResizeInterpolation::linear, cv::INTER_LINEAR},
        {ResizeInterpolation::cubic, cv::INTER_CUBIC},
        {ResizeInterpolation::lanczos4, cv::INTER_LANCZOS4},
    };
    for (const auto* type : {"template_match", "mean_absolute_similarity",
                            "root_mean_square_similarity", "difference_hash_similarity",
                            "histogram_similarity", "perceptual_hash_similarity",
                            "phase_correlation"}) {
        for (const bool roi : {false, true}) {
            write_text(path, reference_scenario(type, roi));
            for (const auto& [interpolation, cv_method] : interpolations) {
                SCOPED_TRACE(std::string{type} + "/" + std::string{to_string(interpolation)} +
                             (roi ? "/roi" : "/full"));
                const auto loaded = load_profile_scenario(path, VideoSourceConfiguration{"", {
                    std::nullopt, ResizeConfiguration{12, 10, interpolation, true},
                }});
                const auto* detector = loaded.scenario.start_condition->detector();
                const auto image = detector->reference_images()[0].image;
                cv::Mat expected;
                const cv::Size size = roi ? cv::Size{6, 4} : cv::Size{12, 10};
                cv::resize(original, expected, size, 0.0, 0.0, cv_method);
                ASSERT_EQ(image.size(), size);
                ASSERT_EQ(image.type(), CV_8UC3);
                EXPECT_EQ(cv::norm(image, expected, cv::NORM_INF), 0.0);
                cv::Mat frame(10, 12, CV_8UC3, cv::Scalar{0, 0, 0});
                if (roi) {
                    expected.copyTo(frame(cv::Rect{3, 2, 6, 4}));
                } else {
                    frame = expected;
                }
                test::ManualTimeProvider clock;
                auto context = test::make_context(frame, clock);
                EXPECT_GT(detector->detect(context).score, 0.99);
            }
        }
    }
}

TEST(ScenarioLoader, ResizesReferencesInNestedConditionsAndAllRuleLocations) {
    TemporaryDirectory directory;
    write_reference(directory.path());
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
start_condition: &condition
  type: all
  conditions:
    - type: detected
      minimum_score: 0.99
      detector: {type: mean_absolute_similarity, reference: reference.png}
reset_condition: *condition
incomplete_condition: *condition
splits:
  - rules:
      - condition: *condition
        action: split
      - sequence:
          - condition: *condition
            action: skip
          - condition: *condition
            action: split
)");
    const auto loaded = load_scenario(path, ReferenceResizeOptions{{12, 10}});
    const auto check = [](const Condition* condition) {
        ASSERT_NE(condition, nullptr);
        const auto image = condition->children()[0]->detector()->reference_images()[0].image;
        EXPECT_EQ(image.size(), cv::Size(12, 10));
    };
    check(loaded.scenario.start_condition.get());
    check(loaded.scenario.reset_condition.get());
    check(loaded.scenario.incomplete_condition.get());
    const auto& rules = *loaded.scenario.splits[0];
    check(rules[0]->active_condition());
    const auto sequence = std::dynamic_pointer_cast<RuleSequence>(rules[1]);
    ASSERT_NE(sequence, nullptr);
    for (const auto& rule : sequence->rules()) {
        check(rule->condition().get());
    }
}

TEST(ScenarioLoader, UInt8InterpolationMatchesPythonReferenceResize) {
    TemporaryDirectory directory;
    cv::Mat original = (cv::Mat_<unsigned char>(2, 3) << 0, 17, 99, 201, 32, 255);
    ASSERT_TRUE(cv::imwrite((directory.path() / "reference.png").string(), original));
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, reference_scenario("mean_absolute_similarity"));
    // Golden pixels from Python resize_scenario_references (uint8), enlargement
    // and reduction. These catch rounding changes from converting to float first.
    struct Example {
        ResizeInterpolation interpolation;
        std::vector<unsigned char> enlarged;
        std::vector<unsigned char> reduced;
    };
    const Example examples[] = {
        {ResizeInterpolation::area, {0, 11, 44, 99, 101, 50, 75, 177, 201, 88, 106, 255}, {75, 126}},
        {ResizeInterpolation::nearest, {0, 0, 17, 99, 0, 0, 17, 99, 201, 201, 32, 255}, {0, 17}},
        {ResizeInterpolation::linear, {0, 11, 48, 99, 101, 53, 82, 177, 201, 95, 116, 255}, {81, 139}},
        {ResizeInterpolation::cubic, {0, 0, 44, 90, 106, 35, 71, 188, 232, 74, 98, 255}, {78, 140}},
        {ResizeInterpolation::lanczos4, {0, 0, 45, 90, 109, 32, 69, 189, 237, 69, 93, 255}, {74, 139}},
    };
    for (const auto& example : examples) {
        SCOPED_TRACE(to_string(example.interpolation));
        for (const bool enlarge : {false, true}) {
            const auto size = enlarge ? OutputSize{4, 3} : OutputSize{2, 1};
            const auto& pixels = enlarge ? example.enlarged : example.reduced;
            const auto loaded = load_scenario(path, ReferenceResizeOptions{size, example.interpolation});
            const auto image = loaded.scenario.start_condition->detector()->reference_images()[0].image;
            const cv::Mat expected = cv::Mat(pixels).reshape(1, size.height);
            ASSERT_EQ(image.type(), CV_8UC1);
            EXPECT_EQ(cv::norm(image, expected, cv::NORM_INF), 0.0);
        }
    }
}

TEST(ScenarioLoader, ProfileValidationAndRuntimeRejectInvalidTransformedReference) {
    TemporaryDirectory directory;
    cv::Mat image(2, 2, CV_8UC4, cv::Scalar{20, 40, 80, 255});
    image.at<cv::Vec4b>(0, 0)[3] = 0;
    ASSERT_TRUE(cv::imwrite((directory.path() / "reference.png").string(), image));
    const auto path = directory.path() / "scenario.yaml";
    Profile profile;
    profile.instances.push_back({{54000}, path.string()});
    profile.source = VideoSourceConfiguration{"", {
        std::nullopt, ResizeConfiguration{3, 3, ResizeInterpolation::linear, true},
    }};
    // The source image has valid binary alpha; interpolation introduces invalid
    // partial alpha, which must be rejected before any capture/Bridge startup.
    for (const auto* type : {"mean_absolute_similarity", "histogram_similarity",
                            "perceptual_hash_similarity"}) {
        SCOPED_TRACE(type);
        write_text(path, reference_scenario(type));
        auto& resize = *std::get<VideoSourceConfiguration>(profile.source).transform.resize;
        resize.resize_references = true;
        EXPECT_NO_THROW((void)load_scenario(path));
        EXPECT_THROW((void)load_profile_scenario(path, profile.source), ConfigurationError);
        Session session;
        EXPECT_THROW(session.apply_profile(profile, AppSettings{}), ConfigurationError);
        EXPECT_FALSE(session.running());
        resize.resize_references = false;
        EXPECT_NO_THROW((void)load_profile_scenario(path, profile.source));
    }
}

TEST(ScenarioLoader, ColorSimilaritiesEvaluateAndExposeDiagnostics) {
    TemporaryDirectory directory;
    const auto image_path = write_reference(directory.path());
    const cv::Mat reference = cv::imread(image_path.string());
    const auto path = directory.path() / "scenario.yaml";
    for (const auto* type : {"histogram_similarity", "perceptual_hash_similarity"}) {
        SCOPED_TRACE(type);
        write_text(path, reference_scenario(type));
        const auto loaded = load_scenario(path);
        const auto* detector = loaded.scenario.start_condition->detector();
        ASSERT_NE(detector, nullptr);
        EXPECT_EQ(detector->type_name(), type);
        EXPECT_EQ(cv::norm(detector->reference_images()[0].image, reference, cv::NORM_INF), 0.0);
        ScenarioRuntime runtime{loaded.scenario};
        runtime.apply_update(LiveSplitUpdate{
            UpdateKind::initial, LiveSplitSnapshot{1, 1, 1, TimerPhase::not_running, -1, 0}, {},
        });
        test::ManualTimeProvider clock;
        EXPECT_FALSE(runtime.evaluate(test::make_context(cv::Mat::zeros(reference.size(), CV_8UC3), clock)));
        const auto action = runtime.evaluate(test::make_context(reference, clock));
        ASSERT_TRUE(action);
        EXPECT_EQ(action->operation, ActionOperation::start);
        const auto diagnostics = runtime.diagnostics();
        ASSERT_TRUE(diagnostics.configuration_valid);
        ASSERT_EQ(diagnostics.rule_errors, 0U);
        ASSERT_EQ(diagnostics.start.size(), 1U);
        ASSERT_EQ(diagnostics.start[0].rules.size(), 1U);
        const auto& condition = diagnostics.start[0].rules[0].condition;
        EXPECT_EQ(condition.detector_type, type);
        EXPECT_EQ(condition.status, "true");
        ASSERT_TRUE(condition.latest_score);
        ASSERT_TRUE(condition.max_score);
        ASSERT_TRUE(condition.minimum_score);
        EXPECT_NEAR(*condition.latest_score, 1.0, 1e-7);
        EXPECT_NEAR(*condition.max_score, 1.0, 1e-7);
        EXPECT_DOUBLE_EQ(*condition.minimum_score, 0.99);
        EXPECT_FALSE(condition.description.empty());
    }
}

TEST(ScenarioLoader, ColorSimilaritiesResizeMaskedReferencesAndKeepOptInBehavior) {
    TemporaryDirectory directory;
    const auto image_path = write_reference(directory.path());
    cv::Mat original;
    cv::cvtColor(cv::imread(image_path.string()), original, cv::COLOR_BGR2BGRA);
    original(cv::Rect{0, 0, 4, 4}).setTo(cv::Scalar{230, 50, 90, 0});
    ASSERT_TRUE(cv::imwrite(image_path.string(), original));
    const auto path = directory.path() / "scenario.yaml";
    for (const auto* type : {"histogram_similarity", "perceptual_hash_similarity"}) {
        for (const bool roi : {false, true}) {
            for (const bool enabled : {false, true}) {
                SCOPED_TRACE(std::string{type} + (roi ? "/roi" : "/full") +
                             (enabled ? "/resize" : "/original"));
                write_text(path, reference_scenario(type, roi));
                const auto loaded = load_profile_scenario(path, VideoSourceConfiguration{"", {
                    std::nullopt, ResizeConfiguration{12, 10, ResizeInterpolation::nearest, enabled},
                }});
                cv::Mat expected;
                const cv::Size size = enabled ? (roi ? cv::Size{6, 4} : cv::Size{12, 10}) : original.size();
                cv::resize(original, expected, size, 0.0, 0.0, cv::INTER_NEAREST);
                const auto* detector = loaded.scenario.start_condition->detector();
                const auto image = detector->reference_images()[0].image;
                EXPECT_EQ(image.type(), CV_8UC4);
                EXPECT_EQ(cv::norm(image, expected, cv::NORM_INF), 0.0);
                // Without resize the original 8x8 mask cannot fit a 6x4 ROI.
                if (roi && !enabled) {
                    continue;
                }
                cv::Mat bgr;
                cv::cvtColor(expected, bgr, cv::COLOR_BGRA2BGR);
                cv::Mat frame;
                if (roi) {
                    frame = cv::Mat::zeros(10, 12, CV_8UC3);
                    bgr.copyTo(frame(cv::Rect{3, 2, 6, 4}));
                } else {
                    frame = bgr;
                }
                test::ManualTimeProvider clock;
                auto context = test::make_context(frame, clock);
                EXPECT_NEAR(detector->detect(context).score, 1.0, 1e-7);
            }
        }
    }
}

TEST(ScenarioLoader, ColorSimilaritiesRejectInvalidYamlAndReferenceFormats) {
    TemporaryDirectory directory;
    const auto image_path = write_reference(directory.path());
    const auto path = directory.path() / "scenario.yaml";
    for (const auto* type : {"histogram_similarity", "perceptual_hash_similarity"}) {
        SCOPED_TRACE(type);
        for (const auto* fields : {"", "    reference: missing.png\n",
                                  "    reference: reference.png\n    hash_size: 8\n",
                                  "    reference: reference.png\n    mystery: 1\n",
                                  "    reference: reference.png\n    roi: {x: 0, y: 0, width: 0, height: 8}\n"}) {
            write_text(path, std::string{"start_condition:\n  type: detected\n  minimum_score: 0.5\n"
                                        "  detector:\n    type: "} + type + "\n" + fields + "splits: []\n");
            EXPECT_THROW((void)load_scenario(path), ScenarioLoadError);
        }
        for (const int format : {CV_8UC1, CV_16UC3}) {
            ASSERT_TRUE(cv::imwrite(image_path.string(), cv::Mat::zeros(8, 8, format)));
            write_text(path, reference_scenario(type));
            EXPECT_THROW((void)load_scenario(path), ScenarioLoadError);
        }
        write_reference(directory.path());
    }
}
