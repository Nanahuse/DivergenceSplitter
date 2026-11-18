#include <gtest/gtest.h>

#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
#include "test_support.hpp"

using namespace divergencesplitter;

namespace {

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

cv::Mat color_texture() {
    cv::Mat image(11, 13, CV_8UC3);
    for (int row = 0; row < image.rows; ++row) {
        for (int column = 0; column < image.cols; ++column) {
            image.at<cv::Vec3b>(row, column) = {
                static_cast<unsigned char>((row * 37 + column * 17 + row * column * 3 + 11) % 256),
                static_cast<unsigned char>((row * 11 + column * 53 + row * column * 5 + 29) % 256),
                static_cast<unsigned char>((row * 71 + column * 7 + row * column * 13 + 47) % 256),
            };
        }
    }
    return image;
}

cv::Mat with_alpha(const cv::Mat& image) {
    cv::Mat reference;
    cv::cvtColor(image, reference, cv::COLOR_BGR2BGRA);
    for (int row = 0; row < reference.rows; ++row) {
        for (int column = 0; column < reference.cols; ++column) {
            reference.at<cv::Vec4b>(row, column)[3] = (row + 2 * column) % 4 != 0 ? 255 : 0;
        }
    }
    return reference;
}

double floating_rms_score(const cv::Mat& frame, const cv::Mat& reference) {
    cv::Mat colors = reference;
    cv::Mat mask;
    if (reference.channels() == 4) {
        cv::cvtColor(reference, colors, cv::COLOR_BGRA2BGR);
        cv::extractChannel(reference, mask, 3);
    }
    cv::Mat frame_float;
    cv::Mat reference_float;
    frame.convertTo(frame_float, CV_64F);
    colors.convertTo(reference_float, CV_64F);
    const auto pixels = mask.empty() ? colors.total() : static_cast<std::size_t>(cv::countNonZero(mask));
    const double components = static_cast<double>(pixels * colors.channels());
    const double total = cv::norm(frame_float, reference_float, cv::NORM_L2SQR, mask);
    return std::clamp(1.0 - (std::sqrt(total) / std::sqrt(components)) / 255.0, 0.0, 1.0);
}

std::array<DetectorPtr, 2> color_similarities(
    const cv::Mat& reference,
    std::optional<Region> roi = std::nullopt
) {
    return {std::make_shared<HistogramSimilarityDetector>(reference, roi),
            std::make_shared<PerceptualHashSimilarityDetector>(reference, roi)};
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

TEST(Detectors, RmsScoresAndThresholdsAgreeWithMaskedPixelDifferences) {
    cv::RNG random(1823);
    test::ManualTimeProvider clock;
    const Region roi{2, 3, 19, 17};
    const auto rectangle = *to_rect(roi);
    for (int iteration = 0; iteration < 8; ++iteration) {
        cv::Mat reference(17, 19, CV_8UC3);
        cv::Mat frame(25, 27, CV_8UC3);
        random.fill(reference, cv::RNG::UNIFORM, 0, 256);
        random.fill(frame, cv::RNG::UNIFORM, 0, 256);
        cv::Mat opaque_reference;
        cv::cvtColor(reference, opaque_reference, cv::COLOR_BGR2BGRA);
        const cv::Mat masked_reference = with_alpha(reference);
        cv::Mat alpha_frame;
        cv::cvtColor(frame, alpha_frame, cv::COLOR_BGR2BGRA);
        cv::Mat alpha(frame.size(), CV_8U);
        random.fill(alpha, cv::RNG::UNIFORM, 0, 256);
        cv::insertChannel(alpha, alpha_frame, 3);

        for (const auto& target : {reference, opaque_reference, masked_reference}) {
            const double expected = floating_rms_score(frame(rectangle), target);
            for (const auto& input : {frame, alpha_frame}) {
                for (const bool use_roi : {false, true}) {
                    SCOPED_TRACE(::testing::Message() << iteration << '/' << target.channels()
                                                     << '/' << input.channels() << '/' << use_roi);
                    const auto detector = std::make_shared<RootMeanSquareSimilarityDetector>(
                        target, use_roi ? std::optional{roi} : std::nullopt);
                    auto context = test::make_context(use_roi ? input : input(rectangle), clock);
                    EXPECT_NEAR(detector->detect(context).score, expected, 1e-12);
                    const auto threshold = [&](double value) {
                        return evaluate_normal(std::make_shared<DetectedCondition>(detector, value), context);
                    };
                    EXPECT_TRUE(threshold(expected - 1e-7));
                    EXPECT_FALSE(threshold(expected + 1e-7));
                }
            }
        }
    }
}

TEST(Detectors, RmsScoresOppositeLargeFramesAsZero) {
    const cv::Mat reference(224, 256, CV_8UC3, cv::Scalar::all(0));
    const cv::Mat frame(reference.size(), CV_8UC3, cv::Scalar::all(255));
    test::ManualTimeProvider clock;
    auto context = test::make_context(frame, clock);
    EXPECT_NEAR(RootMeanSquareSimilarityDetector{reference}.detect(context).score, 0.0, 1e-15);
}

TEST(Detectors, RmsRejectsInvalidReferenceAlphaAndPreservesThePreview) {
    cv::Mat reference(2, 2, CV_8UC4, cv::Scalar{1, 2, 3, 0});
    EXPECT_THROW(RootMeanSquareSimilarityDetector{reference}, std::invalid_argument);
    reference.at<cv::Vec4b>(0, 0)[3] = 128;
    EXPECT_THROW(RootMeanSquareSimilarityDetector{reference}, std::invalid_argument);
    reference.at<cv::Vec4b>(0, 0)[3] = 255;
    RootMeanSquareSimilarityDetector detector{reference};
    const auto original = reference.clone();
    reference.setTo(cv::Scalar::all(0));
    auto displayed = detector.reference_images();
    ASSERT_EQ(displayed.size(), 1U);
    EXPECT_EQ(cv::norm(displayed[0].image, original, cv::NORM_INF), 0.0);
    displayed[0].image.setTo(cv::Scalar::all(0));
    EXPECT_EQ(cv::norm(detector.reference_images()[0].image, original, cv::NORM_INF), 0.0);
}

TEST(Detectors, RmsKeepsFloatingAndMixedDepthInputs) {
    const cv::Mat reference_16(2, 3, CV_16UC3, cv::Scalar{260, 280, 300});
    const cv::Mat frame(2, 3, CV_32FC3, cv::Scalar{230.5, 260.25, 290.125});
    cv::Mat alpha_frame;
    cv::cvtColor(frame, alpha_frame, cv::COLOR_BGR2BGRA);
    const cv::Mat alpha(frame.size(), CV_32F, cv::Scalar{std::numeric_limits<float>::quiet_NaN()});
    cv::insertChannel(alpha, alpha_frame, 3);
    const cv::Mat reference_8 = with_alpha(cv::Mat(frame.size(), CV_8UC3, cv::Scalar{225, 250, 255}));
    test::ManualTimeProvider clock;
    for (const auto& reference : {reference_16, reference_8}) {
        RootMeanSquareSimilarityDetector detector{reference};
        auto context = test::make_context(alpha_frame, clock);
        EXPECT_DOUBLE_EQ(detector.detect(context).score, floating_rms_score(frame, reference));
    }
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

TEST(Detectors, ColorSimilaritiesMatchPythonOpenCv412Goldens) {
    const cv::Mat reference = color_texture();
    cv::Mat patch = reference.clone();
    patch(cv::Rect{3, 2, 5, 4}).setTo(cv::Scalar{250, 15, 90});
    cv::Mat brighter;
    cv::add(reference, cv::Scalar{35, 35, 35}, brighter);
    cv::Mat swapped;
    cv::cvtColor(reference, swapped, cv::COLOR_BGR2RGB);
    cv::Mat inverted;
    cv::bitwise_not(reference, inverted);
    cv::Mat resized;
    cv::resize(reference, resized, cv::Size{19, 7}, 0, 0, cv::INTER_NEAREST);

    // Fixed outputs of the existing Python detectors, opencv-contrib-python
    // 4.12.0.88 (PHash_create), for color_texture() and with_alpha(). Reference
    // hash bytes: BGR [81,129,206,196,93,102,172,124]; masked
    // [45,1,202,213,92,234,169,110]. Compare Hamming distances exactly.
    struct Example {
        const char* name;
        cv::Mat frame;
        double histogram;
        int distance;
        double masked_histogram;
        int masked_distance;
    };
    const Example examples[] = {
        {"identical", reference, 0.9999999894632878, 0, 1.0, 0},
        {"patch", patch, 0.6545477369744437, 20, 0.6362936620829648, 10},
        {"brighter", brighter, 0.11297338559953085, 2, 0.07403079427317694, 4},
        {"swapped", swapped, 0.19619017852552945, 10, 0.16022469952174567, 11},
        {"inverted", inverted, 0.1855420766393402, 64, 0.13858584027789045, 53},
        {"black", cv::Mat::zeros(reference.size(), CV_8UC3), 0.0, 31, 0.0, 32},
        {"white", cv::Mat(reference.size(), CV_8UC3, cv::Scalar{255, 255, 255}), 0.0, 31, 0.0, 30},
        {"resized", resized, 0.588152364357496, 24, 0.0, 0},
    };
    test::ManualTimeProvider clock;
    for (const bool masked : {false, true}) {
        const cv::Mat source = masked ? with_alpha(reference) : reference;
        for (const bool roi : {false, true}) {
            for (const auto& example : examples) {
                if (masked && example.frame.size() != reference.size()) {
                    continue;
                }
                SCOPED_TRACE(std::string{example.name} + (masked ? "/mask" : "/bgr") +
                             (roi ? "/roi" : "/full"));
                const Region region{3, 2, example.frame.cols, example.frame.rows};
                cv::Mat frame;
                if (roi) {
                    frame = cv::Mat(example.frame.rows + 5, example.frame.cols + 7,
                                    CV_8UC3, cv::Scalar{10, 240, 80});
                    example.frame.copyTo(frame(*to_rect(region)));
                } else {
                    frame = example.frame.clone();
                }
                const cv::Mat before = frame.clone();
                auto context = test::make_context(frame, clock);
                const auto detectors = color_similarities(source, roi ? std::optional{region} : std::nullopt);
                EXPECT_NEAR(detectors[0]->detect(context).score,
                            masked ? example.masked_histogram : example.histogram, 1e-7);
                EXPECT_DOUBLE_EQ((1.0 - detectors[1]->detect(context).score) * 64.0,
                                 masked ? example.masked_distance : example.distance);
                EXPECT_EQ(cv::norm(context.frame().image, before, cv::NORM_INF), 0.0);
            }
        }
    }
}

TEST(Detectors, PerceptualHashConstantImagesHaveZeroHash) {
    test::ManualTimeProvider clock;
    PerceptualHashSimilarityDetector detector(cv::Mat::zeros(11, 13, CV_8UC3));
    auto context = test::make_context(cv::Mat(7, 9, CV_8UC3, cv::Scalar{255, 255, 255}), clock);
    EXPECT_DOUBLE_EQ(detector.detect(context).score, 1.0);
}

TEST(Detectors, ColorSimilaritiesIgnoreOnlyTransparentPixels) {
    const cv::Mat reference = color_texture();
    const cv::Mat masked = with_alpha(reference);
    cv::Mat changed = reference.clone();
    for (int row = 0; row < changed.rows; ++row) {
        for (int column = 0; column < changed.cols; ++column) {
            if (masked.at<cv::Vec4b>(row, column)[3] == 0) {
                changed.at<cv::Vec3b>(row, column) = {255, 0, 200};
            }
        }
    }
    cv::Mat opaque;
    cv::cvtColor(reference, opaque, cv::COLOR_BGR2BGRA);
    test::ManualTimeProvider clock;
    auto context = test::make_context(changed, clock);
    const auto masked_detectors = color_similarities(masked);
    const auto opaque_detectors = color_similarities(opaque);
    const auto bgr_detectors = color_similarities(reference);
    for (std::size_t index = 0; index < masked_detectors.size(); ++index) {
        EXPECT_NEAR(masked_detectors[index]->detect(context).score, 1.0, 1e-7);
        EXPECT_LT(bgr_detectors[index]->detect(context).score, 0.99);
        EXPECT_DOUBLE_EQ(opaque_detectors[index]->detect(context).score,
                         bgr_detectors[index]->detect(context).score);
        // Fully opaque alpha behaves like an unmasked BGR reference at any size.
        auto smaller = test::make_context(cv::Mat::zeros(3, 4, CV_8UC3), clock);
        EXPECT_NO_THROW((void)opaque_detectors[index]->detect(smaller));
    }
}

TEST(Detectors, ColorSimilaritiesRejectInvalidImagesMasksAndRegions) {
    const cv::Mat reference = color_texture();
    std::vector<cv::Mat> invalid = {
        {}, cv::Mat(2, 2, CV_8UC1), cv::Mat(2, 2, CV_8UC2), cv::Mat(2, 2, CV_8UC(5)),
        cv::Mat(2, 2, CV_16UC3), cv::Mat(2, 2, CV_32FC3, cv::Scalar{0.5, 1, 2}),
        cv::Mat(2, 2, CV_64FC3, cv::Scalar{std::numeric_limits<double>::quiet_NaN(), 0, 0}),
    };
    const int dimensions[] = {2, 2, 2};
    invalid.emplace_back(3, dimensions, CV_8UC3);
    test::ManualTimeProvider clock;
    const auto detectors = color_similarities(reference);
    for (const auto& image : invalid) {
        EXPECT_THROW((void)HistogramSimilarityDetector(image), std::invalid_argument);
        EXPECT_THROW((void)PerceptualHashSimilarityDetector(image), std::invalid_argument);
        for (const auto& detector : detectors) {
            auto context = test::make_context(image, clock);
            EXPECT_THROW((void)detector->detect(context), std::invalid_argument);
        }
    }
    auto bgra_frame = test::make_context(with_alpha(reference), clock);
    for (const auto& detector : detectors) {
        EXPECT_THROW((void)detector->detect(bgra_frame), std::invalid_argument);
    }
    for (const int alpha : {0, 128}) {
        cv::Mat image(3, 4, CV_8UC4, cv::Scalar{10, 20, 30, static_cast<double>(alpha)});
        EXPECT_THROW((void)HistogramSimilarityDetector(image), std::invalid_argument);
        EXPECT_THROW((void)PerceptualHashSimilarityDetector(image), std::invalid_argument);
    }
    cv::Mat partial = with_alpha(reference);
    partial.at<cv::Vec4b>(0, 0)[3] = 128;
    EXPECT_THROW((void)HistogramSimilarityDetector(partial), std::invalid_argument);
    EXPECT_THROW((void)PerceptualHashSimilarityDetector(partial), std::invalid_argument);
    for (const auto& detector : color_similarities(with_alpha(reference))) {
        auto wrong_size = test::make_context(cv::Mat::zeros(11, 12, CV_8UC3), clock);
        EXPECT_THROW((void)detector->detect(wrong_size), std::invalid_argument);
    }
    for (const Region roi : {Region{-1, 0, 13, 11}, Region{0, 0, 0, 11}, Region{1, 0, 13, 11}}) {
        for (const auto& detector : color_similarities(reference, roi)) {
            auto context = test::make_context(reference, clock);
            EXPECT_THROW((void)detector->detect(context), std::invalid_argument);
        }
    }
    for (const auto& detector : color_similarities(with_alpha(reference), Region{0, 0, 12, 11})) {
        auto context = test::make_context(reference, clock);
        EXPECT_THROW((void)detector->detect(context), std::invalid_argument);
    }
}

TEST(Detectors, ColorSimilarityConditionsMeasureTheirOwnReferenceOnEachFrame) {
    const auto texture = color_texture();
    const auto black = cv::Mat::zeros(texture.size(), CV_8UC3);
    const auto texture_detectors = color_similarities(with_alpha(texture));
    const auto black_detectors = color_similarities(with_alpha(black));
    test::ManualTimeProvider clock;
    auto texture_frame = test::make_context(texture, clock);
    auto black_frame = test::make_context(black, clock);

    for (std::size_t index = 0; index < texture_detectors.size(); ++index) {
        SCOPED_TRACE(texture_detectors[index]->type_name());
        DetectedCondition matches_texture{texture_detectors[index], 0.99};
        DetectedCondition matches_black{black_detectors[index], 0.99};
        EXPECT_EQ(matches_texture.evaluate(texture_frame), true);
        EXPECT_EQ(matches_black.evaluate(texture_frame), false);
        EXPECT_EQ(matches_black.evaluate(black_frame), true);
        EXPECT_EQ(matches_texture.evaluate(black_frame), false);
    }
}

TEST(Detectors, ColorSimilarityReferencePreviewsPreserveTheOriginalPixels) {
    cv::Mat reference = with_alpha(color_texture());
    const auto original = reference.clone();
    const auto detectors = color_similarities(reference);
    reference.setTo(cv::Scalar::all(0));

    for (const auto& detector : detectors) {
        SCOPED_TRACE(detector->type_name());
        auto preview = detector->reference_images();
        ASSERT_EQ(preview.size(), 1U);
        EXPECT_EQ(cv::norm(preview[0].image, original, cv::NORM_INF), 0);
        preview[0].image.setTo(cv::Scalar::all(0));
        preview = detector->reference_images();
        ASSERT_EQ(preview.size(), 1U);
        EXPECT_EQ(cv::norm(preview[0].image, original, cv::NORM_INF), 0);
    }
}
