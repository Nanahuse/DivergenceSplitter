#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "divergencesplitter/condition/condition.hpp"

namespace divergencesplitter {

class DetectedCondition final : public Condition {
public:
    DetectedCondition(DetectorPtr detector, double minimum_score);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "detected"; }
    [[nodiscard]] const Detector* detector() const noexcept override { return detector_.get(); }
    [[nodiscard]] std::optional<double> latest_score() const override { return latest_score_; }
    [[nodiscard]] std::optional<double> max_score() const override { return max_score_; }
    [[nodiscard]] double minimum_score() const noexcept { return minimum_score_; }
    [[nodiscard]] std::string describe() const override;

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    DetectorPtr detector_;
    double minimum_score_{};
    std::optional<double> latest_score_;
    std::optional<double> max_score_;
};

class AllCondition final : public Condition {
public:
    explicit AllCondition(std::vector<ConditionPtr> conditions);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "all"; }
    [[nodiscard]] std::vector<const Condition*> children() const override;
    [[nodiscard]] std::string describe() const override { return "all"; }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    std::vector<ConditionPtr> conditions_;
};

class AnyCondition final : public Condition {
public:
    explicit AnyCondition(std::vector<ConditionPtr> conditions);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "any"; }
    [[nodiscard]] std::vector<const Condition*> children() const override;
    [[nodiscard]] std::string describe() const override { return "any"; }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    std::vector<ConditionPtr> conditions_;
};

class NotCondition final : public Condition {
public:
    explicit NotCondition(ConditionPtr condition);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "not"; }
    [[nodiscard]] std::vector<const Condition*> children() const override;
    [[nodiscard]] std::string describe() const override { return "not"; }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    ConditionPtr condition_;
};

class RisingEdgeCondition final : public Condition {
public:
    explicit RisingEdgeCondition(ConditionPtr condition);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "rising_edge"; }
    [[nodiscard]] std::vector<const Condition*> children() const override;
    [[nodiscard]] std::string describe() const override { return "rising edge"; }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    ConditionPtr condition_;
    std::optional<bool> previous_;
};

class FallingEdgeCondition final : public Condition {
public:
    explicit FallingEdgeCondition(ConditionPtr condition);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "falling_edge"; }
    [[nodiscard]] std::vector<const Condition*> children() const override;
    [[nodiscard]] std::string describe() const override { return "falling edge"; }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    ConditionPtr condition_;
    std::optional<bool> previous_;
};

class OnceCondition final : public Condition {
public:
    explicit OnceCondition(ConditionPtr condition);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "once"; }
    [[nodiscard]] std::vector<const Condition*> children() const override;
    [[nodiscard]] std::string describe() const override { return "once"; }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    ConditionPtr condition_;
    bool completed_{false};
};

class ElapsedCondition final : public Condition {
public:
    explicit ElapsedCondition(std::chrono::nanoseconds duration);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "elapsed"; }
    [[nodiscard]] std::string describe() const override;
    [[nodiscard]] std::chrono::nanoseconds duration() const noexcept { return duration_; }
    [[nodiscard]] std::optional<std::int64_t> elapsed_nanoseconds() const noexcept {
        return elapsed_nanoseconds_;
    }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    std::chrono::nanoseconds duration_;
    std::optional<MonotonicTime> started_at_;
    bool completed_{false};
    std::optional<std::int64_t> elapsed_nanoseconds_;
};

class HoldCondition final : public Condition {
public:
    HoldCondition(ConditionPtr condition, std::chrono::nanoseconds duration);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "hold"; }
    [[nodiscard]] std::vector<const Condition*> children() const override;
    [[nodiscard]] std::string describe() const override;
    [[nodiscard]] std::chrono::nanoseconds duration() const noexcept { return duration_; }
    [[nodiscard]] std::optional<std::int64_t> elapsed_nanoseconds() const noexcept {
        return elapsed_nanoseconds_;
    }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    ConditionPtr condition_;
    std::chrono::nanoseconds duration_;
    std::optional<MonotonicTime> started_at_;
    std::optional<std::int64_t> elapsed_nanoseconds_;
};

class NthCondition final : public Condition {
public:
    NthCondition(ConditionPtr condition, int count);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "nth"; }
    [[nodiscard]] std::vector<const Condition*> children() const override;
    [[nodiscard]] std::string describe() const override;
    [[nodiscard]] int count() const noexcept { return count_; }
    [[nodiscard]] int observed() const noexcept { return observed_; }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    ConditionPtr condition_;
    int count_{};
    int observed_{};
    bool completed_{false};
};

class ResetWhenCondition final : public Condition {
public:
    ResetWhenCondition(ConditionPtr condition, ConditionPtr reset_condition);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "reset_when"; }
    [[nodiscard]] std::vector<const Condition*> children() const override;
    [[nodiscard]] std::string describe() const override { return "reset when"; }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    ConditionPtr condition_;
    ConditionPtr reset_condition_;
};

class ThenCondition final : public Condition {
public:
    ThenCondition(std::vector<ConditionPtr> conditions, std::optional<std::chrono::nanoseconds> within);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "then"; }
    [[nodiscard]] std::vector<const Condition*> children() const override;
    [[nodiscard]] std::string describe() const override;
    [[nodiscard]] std::size_t current_step() const noexcept { return index_; }
    [[nodiscard]] std::size_t step_count() const noexcept { return conditions_.size(); }

protected:
    [[nodiscard]] std::optional<bool> evaluate_impl(FrameContext& context, bool short_circuited) override;
    void reset_state() override;

private:
    std::vector<ConditionPtr> conditions_;
    std::optional<std::chrono::nanoseconds> within_;
    std::size_t index_{};
    std::optional<MonotonicTime> started_at_;
    bool completed_{false};
};

}  // namespace divergencesplitter
