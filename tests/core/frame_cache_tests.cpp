#include <gtest/gtest.h>

#include <barrier>
#include <stdexcept>
#include <thread>

#include "divergencesplitter/frame.hpp"

using namespace divergencesplitter;

TEST(FrameCache, ConcurrentReadersSeeTheSameResultForAKey) {
    FrameCache cache;
    std::barrier start{2};
    DetectionResult left;
    DetectionResult right;
    std::jthread first([&] {
        start.arrive_and_wait();
        left = cache.detection("shared", [] { return DetectionResult{0.25}; });
    });
    std::jthread second([&] {
        start.arrive_and_wait();
        right = cache.detection("shared", [] { return DetectionResult{0.75}; });
    });
    first.join();
    second.join();

    EXPECT_TRUE(left.score == 0.25 || left.score == 0.75);
    EXPECT_DOUBLE_EQ(left.score, right.score);
    EXPECT_DOUBLE_EQ(cache.detection("other", [] { return DetectionResult{0.5}; }).score, 0.5);
    ASSERT_TRUE(cache.cached_detection("shared"));
    EXPECT_DOUBLE_EQ(cache.cached_detection("shared")->score, left.score);
}

TEST(FrameCache, FailedDetectionCanBeRetriedSuccessfully) {
    FrameCache cache;
    const auto failing = []() -> DetectionResult { throw std::runtime_error("boom"); };
    EXPECT_THROW((void)cache.detection("detector", failing), std::runtime_error);
    EXPECT_EQ(cache.cached_detection("detector"), std::nullopt);
    EXPECT_DOUBLE_EQ(cache.detection("detector", [] { return DetectionResult{0.75}; }).score, 0.75);
    EXPECT_DOUBLE_EQ(cache.detection("detector", failing).score, 0.75);
}

TEST(FrameCache, GrayImagesCanBeRetrievedByKey) {
    FrameCache cache;
    const cv::Mat dark(3, 4, CV_8UC1, cv::Scalar{42});
    const cv::Mat light(3, 4, CV_8UC1, cv::Scalar{170});
    (void)cache.gray("dark", [&] { return dark; });
    (void)cache.gray("light", [&] { return light; });

    for (const auto& [key, expected] : {std::pair{"dark", dark}, std::pair{"light", light}}) {
        SCOPED_TRACE(key);
        const auto cached = cache.cached_gray(key);
        ASSERT_TRUE(cached);
        ASSERT_EQ(cached->size(), expected.size());
        ASSERT_EQ(cached->type(), expected.type());
        EXPECT_EQ(cv::norm(*cached, expected, cv::NORM_INF), 0);
    }
}
