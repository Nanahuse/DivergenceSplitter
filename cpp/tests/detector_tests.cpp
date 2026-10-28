#include <gtest/gtest.h>

#include <opencv2/imgproc.hpp>

#include <cstring>
#include <memory>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
#include "test_support.hpp"

using namespace divergencesplitter;

namespace {

class CountingDetector final : public Detector {
public:
    explicit CountingDetector(std::shared_ptr<int> calls) : calls_(std::move(calls)) {}

    [[nodiscard]] std::string_view type_name() const noexcept override { return "counting"; }
    [[nodiscard]] std::string cache_key() const override { return "counting:stable"; }
    [[nodiscard]] DetectionResult detect(FrameContext&) const override {
        ++*calls_;
        return DetectionResult{1.0};
    }

private:
    std::shared_ptr<int> calls_;
};

cv::Mat gradient(int width, int height) {
    cv::Mat image(height, width, CV_8UC1);
    for (int row = 0; row < height; ++row) {
        for (int column = 0; column < width; ++column) {
            image.at<unsigned char>(row, column) =
                static_cast<unsigned char>((row * 7 + column * 13) % 256);
        }
    }
    return image;
}

}  // namespace

TEST(Detectors, MeanBrightness) {
    test::ManualTimeProvider clock;
    auto context = test::make_context(test::solid(8, 8, 200), clock);
    MeanBrightnessDetector detector;
    const auto result = detector.detect(context);
    EXPECT_NEAR(result.score, 200.0 / 255.0, 1e-9);
}

TEST(Detectors, ColorRangeRatio) {
    test::ManualTimeProvider clock;
    cv::Mat image(10, 10, CV_8UC3, cv::Scalar{0, 0, 0});
    image.rowRange(0, 2).setTo(cv::Scalar{0, 0, 255});
    auto context = test::make_context(image, clock);
    ColorRangeDetector detector({0.0, 0.0, 200.0}, {10.0, 10.0, 255.0});
    EXPECT_NEAR(detector.detect(context).score, 0.2, 1e-9);
}

TEST(Detectors, TemplateMatchFindsExactPatch) {
    test::ManualTimeProvider clock;
    const unsigned char pattern[9] = {0, 255, 0, 255, 0, 255, 0, 255, 0};
    cv::Mat templ(3, 3, CV_8UC1);
    std::memcpy(templ.data, pattern, sizeof(pattern));
    cv::Mat frame(20, 20, CV_8UC1, cv::Scalar{0});
    templ.copyTo(frame(cv::Rect{8, 8, 3, 3}));

    auto context = test::make_context(frame, clock);
    TemplateMatchDetector detector(templ.clone());
    EXPECT_GT(detector.detect(context).score, 0.99);
}

TEST(Detectors, SimilarityDetectorsScoreMatches) {
    test::ManualTimeProvider clock;
    cv::Mat image(2, 2, CV_8UC1);
    image.at<unsigned char>(0, 0) = 10;
    image.at<unsigned char>(0, 1) = 20;
    image.at<unsigned char>(1, 0) = 30;
    image.at<unsigned char>(1, 1) = 40;
    auto context = test::make_context(image, clock);

    MeanAbsoluteSimilarityDetector absolute(image.clone());
    RootMeanSquareSimilarityDetector rms(image.clone());
    EXPECT_NEAR(absolute.detect(context).score, 1.0, 1e-9);
    EXPECT_NEAR(rms.detect(context).score, 1.0, 1e-9);

    cv::Mat different = image.clone();
    different += 100;
    auto different_context = test::make_context(different, clock);
    EXPECT_NEAR(absolute.detect(different_context).score, 1.0 - 100.0 / 255.0, 1e-9);
    EXPECT_NEAR(rms.detect(different_context).score, 1.0 - 100.0 / 255.0, 1e-9);
}

TEST(Detectors, DifferenceHash) {
    test::ManualTimeProvider clock;
    cv::Mat image = gradient(16, 16);
    DifferenceHashSimilarityDetector detector(image.clone(), 8);
    auto context = test::make_context(image, clock);
    EXPECT_NEAR(detector.detect(context).score, 1.0, 1e-9);

    cv::Mat inverted;
    cv::bitwise_not(image, inverted);
    auto inverted_context = test::make_context(inverted, clock);
    EXPECT_LT(detector.detect(inverted_context).score, 0.1);
}

TEST(Detectors, PhaseCorrelation) {
    test::ManualTimeProvider clock;
    cv::Mat image = gradient(32, 32);
    PhaseCorrelationDetector detector(image.clone());
    auto context = test::make_context(image, clock);
    EXPECT_GT(detector.detect(context).score, 0.99);
}

TEST(Detectors, EquivalentDetectorsShareFrameCache) {
    auto calls = std::make_shared<int>(0);
    DetectedCondition first(std::make_shared<CountingDetector>(calls), 0.5);
    DetectedCondition second(std::make_shared<CountingDetector>(calls), 0.5);

    test::ManualTimeProvider clock;
    auto shared = std::make_shared<SharedFrameEvaluation>(
        SharedFrameEvaluation{
            Frame{test::solid(2, 2, 0), clock.now()},
            clock.now(),
            {},
        }
    );
    FrameContext context{shared};
    EXPECT_TRUE(evaluate_normal(std::shared_ptr<Condition>(&first, [](Condition*) {}), context));
    EXPECT_TRUE(evaluate_normal(std::shared_ptr<Condition>(&second, [](Condition*) {}), context));
    EXPECT_EQ(*calls, 1);
}

TEST(Detectors, TemplateWithAlphaUsesMask) {
    test::ManualTimeProvider clock;
    cv::Mat reference(3, 3, CV_8UC4, cv::Scalar{0, 0, 0, 0});
    reference.at<cv::Vec4b>(0, 0) = {255, 255, 255, 255};
    reference.at<cv::Vec4b>(1, 1) = {0, 0, 0, 255};
    reference.at<cv::Vec4b>(2, 2) = {255, 0, 0, 255};

    TemplateMatchDetector detector(reference.clone());
    cv::Mat frame(10, 10, CV_8UC3, cv::Scalar{0, 0, 0});
    cv::Mat bgr;
    cv::cvtColor(reference, bgr, cv::COLOR_BGRA2BGR);
    bgr.copyTo(frame(cv::Rect{4, 4, 3, 3}));
    auto context = test::make_context(frame, clock);
    const auto score = detector.detect(context).score;
    EXPECT_GE(score, 0.0);
    EXPECT_LE(score, 1.0);
}
