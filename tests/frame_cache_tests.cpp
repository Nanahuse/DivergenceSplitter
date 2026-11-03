#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <stdexcept>
#include <thread>

#include "divergencesplitter/frame.hpp"
#include "test_support.hpp"

using namespace divergencesplitter;

TEST(FrameCache, DetectionIsComputedOnce) {
    FrameCache cache;
    int calls = 0;
    const auto compute = [&calls]() {
        ++calls;
        return DetectionResult{0.75};
    };
    const auto first = cache.detection("detector", compute);
    const auto second = cache.detection("detector", compute);
    EXPECT_DOUBLE_EQ(first.score, 0.75);
    EXPECT_DOUBLE_EQ(second.score, 0.75);
    EXPECT_EQ(calls, 1);
    EXPECT_TRUE(cache.has_detection("detector"));
    EXPECT_TRUE(cache.cached_detection("detector").has_value());
}

TEST(FrameCache, ConcurrentRequestsShareOneComputation) {
    FrameCache cache;
    std::atomic_int calls{0};
    const auto compute = [&calls]() {
        ++calls;
        std::this_thread::sleep_for(std::chrono::milliseconds{40});
        return DetectionResult{0.5};
    };
    std::optional<DetectionResult> left;
    std::optional<DetectionResult> right;
    std::thread first([&]() { left = cache.detection("shared", compute); });
    std::thread second([&]() { right = cache.detection("shared", compute); });
    first.join();
    second.join();
    EXPECT_EQ(calls.load(), 1);
    ASSERT_TRUE(left.has_value());
    ASSERT_TRUE(right.has_value());
}

TEST(FrameCache, FailuresAreNotCached) {
    FrameCache cache;
    int calls = 0;
    const auto failing = [&calls]() -> DetectionResult {
        ++calls;
        throw std::runtime_error("boom");
    };
    EXPECT_THROW((void)cache.detection("failing", failing), std::runtime_error);
    EXPECT_FALSE(cache.has_detection("failing"));
    EXPECT_THROW((void)cache.detection("failing", failing), std::runtime_error);
    EXPECT_EQ(calls, 2);
}

TEST(FrameCache, GrayImagesAreCachedPerKey) {
    FrameCache cache;
    int calls = 0;
    cv::Mat source = test::solid(4, 3, 42);
    const auto compute = [&]() {
        ++calls;
        return source.clone();
    };
    const auto first = cache.gray("gray", compute);
    const auto second = cache.gray("gray", compute);
    EXPECT_EQ(first.rows, 3);
    EXPECT_EQ(second.cols, 4);
    EXPECT_EQ(calls, 1);
    EXPECT_TRUE(cache.cached_gray("gray").has_value());
}

TEST(FrameCache, ContextsShareTheSameFrameCache) {
    auto shared = std::make_shared<SharedFrameEvaluation>(
        SharedFrameEvaluation{
            Frame{test::solid(2, 2, 10), MonotonicTime{0}},
            MonotonicTime{0},
            {},
        }
    );
    FrameContext first{shared};
    FrameContext second{shared};
    int calls = 0;
    const auto compute = [&calls]() {
        ++calls;
        return DetectionResult{0.1};
    };
    (void)first.cache().detection("key", compute);
    (void)second.cache().detection("key", compute);
    EXPECT_EQ(calls, 1);
}
