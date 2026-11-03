#include <gtest/gtest.h>

#include <memory>
#include <string>

#include "divergencesplitter/condition/conditions.hpp"
#include "test_support.hpp"

using namespace divergencesplitter;

namespace {

class MutableScoreDetector final : public Detector {
public:
    MutableScoreDetector(std::shared_ptr<double> score, std::string key)
        : score_(std::move(score)), key_(std::move(key)) {}

    [[nodiscard]] std::string_view type_name() const noexcept override { return "mutable"; }
    [[nodiscard]] std::string cache_key() const override { return key_; }
    [[nodiscard]] DetectionResult detect(FrameContext&) const override {
        return DetectionResult{*score_};
    }

private:
    std::shared_ptr<double> score_;
    std::string key_;
};

ConditionPtr detected(std::shared_ptr<double> score, double minimum, std::string key) {
    return std::make_shared<DetectedCondition>(
        std::make_shared<MutableScoreDetector>(std::move(score), std::move(key)),
        minimum
    );
}

}  // namespace

TEST(Conditions, DetectedAndNot) {
    auto score = std::make_shared<double>(0.8);
    test::ManualTimeProvider clock;
    auto context = test::make_context(test::solid(2, 2, 10), clock);

    auto condition = detected(score, 0.5, "a");
    EXPECT_TRUE(evaluate_normal(condition, context));
    EXPECT_EQ(condition->status(), ConditionStatus::true_value);

    auto inverted = std::make_shared<NotCondition>(condition);
    EXPECT_FALSE(evaluate_normal(inverted, context));
}

TEST(Conditions, AllAndAnyShortCircuit) {
    auto high = std::make_shared<double>(1.0);
    auto low = std::make_shared<double>(0.0);
    test::ManualTimeProvider clock;
    auto context = test::make_context(test::solid(2, 2, 10), clock);

    auto yes = detected(high, 0.5, "yes");
    auto no = detected(low, 0.5, "no");
    auto all = std::make_shared<AllCondition>(std::vector<ConditionPtr>{yes, no});
    EXPECT_FALSE(evaluate_normal(all, context));

    auto any = std::make_shared<AnyCondition>(std::vector<ConditionPtr>{yes, no});
    EXPECT_TRUE(evaluate_normal(any, context));
    EXPECT_EQ(no->status(), ConditionStatus::skipped);
}

TEST(Conditions, RisingAndFallingEdges) {
    auto score = std::make_shared<double>(0.0);
    test::ManualTimeProvider clock;
    auto child = detected(score, 0.5, "edge");
    auto rising = std::make_shared<RisingEdgeCondition>(child);
    auto falling = std::make_shared<FallingEdgeCondition>(child);

    auto first = test::make_context(test::solid(2, 2, 10), clock);
    EXPECT_FALSE(evaluate_normal(rising, first));
    EXPECT_FALSE(evaluate_normal(falling, first));

    *score = 1.0;
    clock.advance(std::chrono::milliseconds{10});
    auto second = test::make_context(test::solid(2, 2, 10), clock);
    EXPECT_TRUE(evaluate_normal(rising, second));
    EXPECT_FALSE(evaluate_normal(falling, second));

    *score = 0.0;
    clock.advance(std::chrono::milliseconds{10});
    auto third = test::make_context(test::solid(2, 2, 10), clock);
    EXPECT_FALSE(evaluate_normal(rising, third));
    EXPECT_TRUE(evaluate_normal(falling, third));
}

TEST(Conditions, OnceAndNth) {
    auto score = std::make_shared<double>(1.0);
    test::ManualTimeProvider clock;
    auto once = std::make_shared<OnceCondition>(detected(score, 0.5, "once"));
    EXPECT_TRUE(evaluate_normal(once, test::make_context(test::solid(2, 2, 0), clock)));
    EXPECT_TRUE(evaluate_normal(once, test::make_context(test::solid(2, 2, 0), clock)));

    auto nth = std::make_shared<NthCondition>(detected(score, 0.5, "nth"), 3);
    EXPECT_FALSE(evaluate_normal(nth, test::make_context(test::solid(2, 2, 0), clock)));
    EXPECT_FALSE(evaluate_normal(nth, test::make_context(test::solid(2, 2, 0), clock)));
    EXPECT_TRUE(evaluate_normal(nth, test::make_context(test::solid(2, 2, 0), clock)));
    EXPECT_FALSE(evaluate_normal(nth, test::make_context(test::solid(2, 2, 0), clock)));
}

TEST(Conditions, ElapsedStartsOnFirstEvaluation) {
    test::ManualTimeProvider clock;
    auto condition = std::make_shared<ElapsedCondition>(std::chrono::seconds{1});
    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
    clock.advance(std::chrono::milliseconds{999});
    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
    clock.advance(std::chrono::milliseconds{1});
    EXPECT_TRUE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
}

TEST(Conditions, HoldRequiresContinuousTruth) {
    auto score = std::make_shared<double>(1.0);
    test::ManualTimeProvider clock;
    auto condition = std::make_shared<HoldCondition>(
        detected(score, 0.5, "hold"),
        std::chrono::seconds{1}
    );
    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
    clock.advance(std::chrono::milliseconds{500});
    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));

    *score = 0.0;
    clock.advance(std::chrono::milliseconds{100});
    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));

    *score = 1.0;
    clock.advance(std::chrono::milliseconds{500});
    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
    clock.advance(std::chrono::milliseconds{500});
    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
    clock.advance(std::chrono::milliseconds{500});
    EXPECT_TRUE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
}

TEST(Conditions, ThenWalksSteps) {
    auto score = std::make_shared<double>(1.0);
    test::ManualTimeProvider clock;
    auto first = detected(score, 0.5, "then-first");
    auto second = std::make_shared<ElapsedCondition>(std::chrono::milliseconds{500});
    auto condition = std::make_shared<ThenCondition>(
        std::vector<ConditionPtr>{first, second},
        std::nullopt
    );

    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
    EXPECT_EQ(condition->current_step(), 1);
    clock.advance(std::chrono::milliseconds{500});
    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
    clock.advance(std::chrono::milliseconds{500});
    EXPECT_TRUE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
}

TEST(Conditions, ThenWithinExpires) {
    auto score = std::make_shared<double>(1.0);
    test::ManualTimeProvider clock;
    auto first = detected(score, 0.5, "within-first");
    auto second = detected(score, 0.5, "within-second");
    auto condition = std::make_shared<ThenCondition>(
        std::vector<ConditionPtr>{first, second},
        std::chrono::milliseconds{100}
    );

    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
    EXPECT_EQ(condition->current_step(), 1);
    clock.advance(std::chrono::milliseconds{200});
    EXPECT_FALSE(evaluate_normal(condition, test::make_context(test::solid(2, 2, 0), clock)));
    EXPECT_EQ(condition->current_step(), 1);
}

TEST(Conditions, ResetWhenResetsChildState) {
    auto child_score = std::make_shared<double>(1.0);
    auto reset_score = std::make_shared<double>(0.0);
    test::ManualTimeProvider clock;
    auto reset = std::make_shared<ResetWhenCondition>(
        std::make_shared<OnceCondition>(detected(child_score, 0.5, "reset-child")),
        detected(reset_score, 0.5, "reset-condition")
    );

    EXPECT_TRUE(evaluate_normal(reset, test::make_context(test::solid(2, 2, 0), clock)));
    *child_score = 0.0;
    *reset_score = 1.0;
    EXPECT_FALSE(evaluate_normal(reset, test::make_context(test::solid(2, 2, 0), clock)));
    *reset_score = 0.0;
    EXPECT_FALSE(evaluate_normal(reset, test::make_context(test::solid(2, 2, 0), clock)));
}

TEST(Conditions, SkippedStatusPropagates) {
    auto high = std::make_shared<double>(1.0);
    auto low = std::make_shared<double>(0.0);
    test::ManualTimeProvider clock;
    auto context = test::make_context(test::solid(2, 2, 0), clock);
    auto child = std::make_shared<AllCondition>(std::vector<ConditionPtr>{
        detected(low, 0.5, "skip-first"),
        detected(high, 0.5, "skip-second"),
    });
    EXPECT_FALSE(evaluate_normal(child, context));
    EXPECT_EQ(child->children()[1]->status(), ConditionStatus::skipped);
}
