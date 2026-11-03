#include <gtest/gtest.h>

#include "divergencesplitter/capture/normalizer.hpp"
#include "test_support.hpp"

using namespace divergencesplitter;

TEST(Normalizer, CropsAndResizes) {
    FrameNormalizer normalizer(
        CropMargins{10, 10, 5, 5},
        OutputSize{40, 20},
        ResizeInterpolation::linear
    );
    const auto output = normalizer.normalize(test::solid(100, 50, 128));
    EXPECT_EQ(output.cols, 40);
    EXPECT_EQ(output.rows, 20);
}

TEST(Normalizer, RejectsCropThatDoesNotFit) {
    FrameNormalizer normalizer(CropMargins{60, 60, 0, 0});
    EXPECT_THROW(
        (void)normalizer.normalize(test::solid(100, 50, 0)),
        FrameNormalizationError
    );
}

TEST(Normalizer, PassthroughWhenUnconfigured) {
    FrameNormalizer normalizer;
    const auto input = test::solid(17, 9, 10);
    const auto output = normalizer.normalize(input);
    EXPECT_EQ(output.cols, 17);
    EXPECT_EQ(output.rows, 9);
}

TEST(Normalizer, CropOnly) {
    FrameNormalizer normalizer(CropMargins{2, 3, 4, 5});
    const auto output = normalizer.normalize(test::solid(20, 30, 0));
    EXPECT_EQ(output.cols, 15);
    EXPECT_EQ(output.rows, 21);
}
