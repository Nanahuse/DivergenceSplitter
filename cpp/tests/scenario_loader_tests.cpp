#include <gtest/gtest.h>

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <filesystem>
#include <fstream>
#include <string>

#include "divergencesplitter/scenario/scenario.hpp"
#include "divergencesplitter/runtime/session.hpp"
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
    const auto image_path = write_reference(directory.path());
    const auto original = cv::imread(image_path.string(), cv::IMREAD_UNCHANGED);
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
                            "phase_correlation"}) {
        for (const bool roi : {false, true}) {
            write_text(path, reference_scenario(type, roi));
            for (const auto& [interpolation, cv_method] : interpolations) {
                SCOPED_TRACE(std::string{type} + "/" + std::string{to_string(interpolation)} +
                             (roi ? "/roi" : "/full"));
                const auto loaded = load_scenario(path, ReferenceResizeOptions{{12, 10}, interpolation});
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
    write_text(path, reference_scenario("mean_absolute_similarity"));
    Profile profile;
    profile.instances.push_back({{54000}, path.string()});
    profile.source = VideoSourceConfiguration{"", {
        std::nullopt, ResizeConfiguration{3, 3, ResizeInterpolation::linear, true},
    }};
    // The source image has valid binary alpha; interpolation introduces invalid
    // partial alpha, which must be rejected before any capture/Bridge startup.
    EXPECT_NO_THROW((void)load_scenario(path));
    EXPECT_THROW((void)load_profile_scenario(path, profile.source), ConfigurationError);
    Session session;
    EXPECT_THROW(session.apply_profile(profile, AppSettings{}), ConfigurationError);
    EXPECT_FALSE(session.running());
    std::get<VideoSourceConfiguration>(profile.source).transform.resize->resize_references = false;
    EXPECT_NO_THROW((void)load_profile_scenario(path, profile.source));
}
