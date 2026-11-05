#include "divergencesplitter/condition/conditions.hpp"

#include <algorithm>
#include <cmath>
#include <sstream>
#include <stdexcept>
#include <string>

#include "divergencesplitter/detector/detector.hpp"

namespace divergencesplitter {
namespace {

std::string format_duration(std::chrono::nanoseconds duration) {
    const auto milliseconds = duration.count() / 1'000'000;
    if (milliseconds % 1000 == 0) {
        return std::to_string(milliseconds / 1000) + "s";
    }
    return std::to_string(milliseconds) + "ms";
}

}  // namespace

std::string_view to_string(ConditionStatus status) noexcept {
    switch (status) {
        case ConditionStatus::not_evaluated:
            return "not_evaluated";
        case ConditionStatus::true_value:
            return "true";
        case ConditionStatus::false_value:
            return "false";
        case ConditionStatus::skipped:
            return "skipped";
        case ConditionStatus::error:
            return "error";
    }
    return "unknown";
}

std::optional<bool> Condition::evaluate(FrameContext& context, bool short_circuited) {
    try {
        const auto result = evaluate_impl(context, short_circuited);
        if (short_circuited) {
            status_ = ConditionStatus::skipped;
            return result;
        }
        if (!result.has_value()) {
            status_ = ConditionStatus::error;
            throw std::logic_error("condition did not return a boolean result");
        }
        status_ = *result ? ConditionStatus::true_value : ConditionStatus::false_value;
        return result;
    } catch (...) {
        status_ = ConditionStatus::error;
        throw;
    }
}

void Condition::reset() {
    status_ = ConditionStatus::not_evaluated;
    reset_state();
}

void Condition::mark_skipped() const {
    status_ = ConditionStatus::skipped;
    for (const auto* child : children()) {
        if (child != nullptr) {
            child->mark_skipped();
        }
    }
}

bool evaluate_normal(const ConditionPtr& condition, FrameContext context) {
    const auto result = condition->evaluate(context);
    if (!result.has_value()) {
        throw std::logic_error("condition returned no value during normal evaluation");
    }
    return *result;
}

void evaluate_short(const ConditionPtr& condition, FrameContext context) {
    (void)condition->evaluate(context, true);
}

void reset_all(const std::vector<ConditionPtr>& conditions) {
    for (const auto& condition : conditions) {
        condition->reset();
    }
}

DetectedCondition::DetectedCondition(DetectorPtr detector, double minimum_score)
    : detector_(std::move(detector)), minimum_score_(minimum_score) {
    if (!detector_) {
        throw std::invalid_argument("detector must not be null");
    }
    if (!std::isfinite(minimum_score_)) {
        throw std::invalid_argument("minimum_score must be finite");
    }
}

std::string DetectedCondition::describe() const {
    std::ostringstream stream;
    stream << "detected >= " << minimum_score_;
    if (detector_) {
        stream << " (" << detector_->type_name() << ')';
    }
    return stream.str();
}

std::optional<bool> DetectedCondition::evaluate_impl(
    FrameContext& context,
    bool short_circuited
) {
    if (short_circuited) {
        return std::nullopt;
    }
    const double score = detect_cached(context, detector_).score;
    latest_score_ = score;
    if (!max_score_.has_value() || score > *max_score_) {
        max_score_ = score;
    }
    return score >= minimum_score_;
}

void DetectedCondition::reset_state() {
    latest_score_.reset();
    max_score_.reset();
}

AllCondition::AllCondition(std::vector<ConditionPtr> conditions)
    : conditions_(std::move(conditions)) {}

std::vector<const Condition*> AllCondition::children() const {
    std::vector<const Condition*> result;
    result.reserve(conditions_.size());
    for (const auto& condition : conditions_) {
        result.push_back(condition.get());
    }
    return result;
}

std::optional<bool> AllCondition::evaluate_impl(FrameContext& context, bool short_circuited) {
    if (short_circuited) {
        for (const auto& condition : conditions_) {
            evaluate_short(condition, context);
        }
        return std::nullopt;
    }
    bool result = true;
    for (const auto& condition : conditions_) {
        if (result) {
            result = evaluate_normal(condition, context);
        } else {
            evaluate_short(condition, context);
        }
    }
    return result;
}

void AllCondition::reset_state() {
    reset_all(conditions_);
}

AnyCondition::AnyCondition(std::vector<ConditionPtr> conditions)
    : conditions_(std::move(conditions)) {}

std::vector<const Condition*> AnyCondition::children() const {
    std::vector<const Condition*> result;
    result.reserve(conditions_.size());
    for (const auto& condition : conditions_) {
        result.push_back(condition.get());
    }
    return result;
}

std::optional<bool> AnyCondition::evaluate_impl(FrameContext& context, bool short_circuited) {
    if (short_circuited) {
        for (const auto& condition : conditions_) {
            evaluate_short(condition, context);
        }
        return std::nullopt;
    }
    bool result = false;
    for (const auto& condition : conditions_) {
        if (result) {
            evaluate_short(condition, context);
        } else {
            result = evaluate_normal(condition, context);
        }
    }
    return result;
}

void AnyCondition::reset_state() {
    reset_all(conditions_);
}

NotCondition::NotCondition(ConditionPtr condition) : condition_(std::move(condition)) {
    if (!condition_) {
        throw std::invalid_argument("condition must not be null");
    }
}

std::vector<const Condition*> NotCondition::children() const {
    return {condition_.get()};
}

std::optional<bool> NotCondition::evaluate_impl(FrameContext& context, bool short_circuited) {
    if (short_circuited) {
        evaluate_short(condition_, context);
        return std::nullopt;
    }
    return !evaluate_normal(condition_, context);
}

void NotCondition::reset_state() {
    condition_->reset();
}

RisingEdgeCondition::RisingEdgeCondition(ConditionPtr condition)
    : condition_(std::move(condition)) {
    if (!condition_) {
        throw std::invalid_argument("condition must not be null");
    }
}

std::vector<const Condition*> RisingEdgeCondition::children() const {
    return {condition_.get()};
}

std::optional<bool> RisingEdgeCondition::evaluate_impl(
    FrameContext& context,
    bool short_circuited
) {
    const bool current = evaluate_normal(condition_, context);
    const auto previous = previous_;
    previous_ = current;
    const bool fired = previous.has_value() && !*previous && current;
    return short_circuited ? std::nullopt : std::optional<bool>{fired};
}

void RisingEdgeCondition::reset_state() {
    previous_.reset();
    condition_->reset();
}

FallingEdgeCondition::FallingEdgeCondition(ConditionPtr condition)
    : condition_(std::move(condition)) {
    if (!condition_) {
        throw std::invalid_argument("condition must not be null");
    }
}

std::vector<const Condition*> FallingEdgeCondition::children() const {
    return {condition_.get()};
}

std::optional<bool> FallingEdgeCondition::evaluate_impl(
    FrameContext& context,
    bool short_circuited
) {
    const bool current = evaluate_normal(condition_, context);
    const auto previous = previous_;
    previous_ = current;
    const bool fired = previous.has_value() && *previous && !current;
    return short_circuited ? std::nullopt : std::optional<bool>{fired};
}

void FallingEdgeCondition::reset_state() {
    previous_.reset();
    condition_->reset();
}

OnceCondition::OnceCondition(ConditionPtr condition) : condition_(std::move(condition)) {
    if (!condition_) {
        throw std::invalid_argument("condition must not be null");
    }
}

std::vector<const Condition*> OnceCondition::children() const {
    return {condition_.get()};
}

std::optional<bool> OnceCondition::evaluate_impl(FrameContext& context, bool short_circuited) {
    if (completed_) {
        condition_->mark_skipped();
        return short_circuited ? std::nullopt : std::optional<bool>{true};
    }
    const bool current = evaluate_normal(condition_, context);
    if (current) {
        completed_ = true;
    }
    return short_circuited ? std::nullopt : std::optional<bool>{current};
}

void OnceCondition::reset_state() {
    completed_ = false;
    condition_->reset();
}

ElapsedCondition::ElapsedCondition(std::chrono::nanoseconds duration) : duration_(duration) {
    if (duration_.count() < 0) {
        throw std::invalid_argument("duration must be non-negative");
    }
}

std::string ElapsedCondition::describe() const {
    return "elapsed " + format_duration(duration_);
}

std::optional<bool> ElapsedCondition::evaluate_impl(
    FrameContext& context,
    bool short_circuited
) {
    if (completed_) {
        return short_circuited ? std::nullopt : std::optional<bool>{true};
    }
    if (started_at_.has_value() && context.now() < *started_at_) {
        throw std::invalid_argument("monotonic time moved backwards");
    }
    if (!started_at_.has_value()) {
        started_at_ = context.now();
    }
    const auto elapsed = (context.now() - *started_at_).count();
    elapsed_nanoseconds_ = std::min<std::int64_t>(elapsed, duration_.count());
    if (elapsed >= duration_.count()) {
        completed_ = true;
    }
    return short_circuited ? std::nullopt : std::optional<bool>{completed_};
}

void ElapsedCondition::reset_state() {
    started_at_.reset();
    completed_ = false;
    elapsed_nanoseconds_.reset();
}

HoldCondition::HoldCondition(ConditionPtr condition, std::chrono::nanoseconds duration)
    : condition_(std::move(condition)), duration_(duration) {
    if (!condition_) {
        throw std::invalid_argument("condition must not be null");
    }
    if (duration_.count() < 0) {
        throw std::invalid_argument("duration must be non-negative");
    }
}

std::vector<const Condition*> HoldCondition::children() const {
    return {condition_.get()};
}

std::string HoldCondition::describe() const {
    return "hold " + format_duration(duration_);
}

std::optional<bool> HoldCondition::evaluate_impl(FrameContext& context, bool short_circuited) {
    const bool current = evaluate_normal(condition_, context);
    if (started_at_.has_value() && context.now() < *started_at_) {
        throw std::invalid_argument("monotonic time moved backwards");
    }
    bool result = false;
    if (!current) {
        started_at_.reset();
        elapsed_nanoseconds_ = 0;
    } else {
        if (!started_at_.has_value()) {
            started_at_ = context.now();
        }
        const auto elapsed = (context.now() - *started_at_).count();
        elapsed_nanoseconds_ = std::min<std::int64_t>(elapsed, duration_.count());
        result = elapsed >= duration_.count();
    }
    return short_circuited ? std::nullopt : std::optional<bool>{result};
}

void HoldCondition::reset_state() {
    started_at_.reset();
    elapsed_nanoseconds_.reset();
    condition_->reset();
}

NthCondition::NthCondition(ConditionPtr condition, int count)
    : condition_(std::move(condition)), count_(count) {
    if (!condition_) {
        throw std::invalid_argument("condition must not be null");
    }
    if (count_ < 1) {
        throw std::invalid_argument("count must be a positive integer");
    }
}

std::vector<const Condition*> NthCondition::children() const {
    return {condition_.get()};
}

std::string NthCondition::describe() const {
    return "nth " + std::to_string(count_);
}

std::optional<bool> NthCondition::evaluate_impl(FrameContext& context, bool short_circuited) {
    if (completed_) {
        condition_->mark_skipped();
        return short_circuited ? std::nullopt : std::optional<bool>{false};
    }
    const bool current = evaluate_normal(condition_, context);
    bool fired = false;
    if (current) {
        ++observed_;
        if (observed_ == count_) {
            completed_ = true;
            fired = true;
        }
    }
    return short_circuited ? std::nullopt : std::optional<bool>{fired};
}

void NthCondition::reset_state() {
    observed_ = 0;
    completed_ = false;
    condition_->reset();
}

ResetWhenCondition::ResetWhenCondition(ConditionPtr condition, ConditionPtr reset_condition)
    : condition_(std::move(condition)), reset_condition_(std::move(reset_condition)) {
    if (!condition_ || !reset_condition_) {
        throw std::invalid_argument("conditions must not be null");
    }
}

std::vector<const Condition*> ResetWhenCondition::children() const {
    return {condition_.get(), reset_condition_.get()};
}

std::optional<bool> ResetWhenCondition::evaluate_impl(
    FrameContext& context,
    bool short_circuited
) {
    const bool should_reset = evaluate_normal(reset_condition_, context);
    if (should_reset) {
        reset();
    }
    if (short_circuited) {
        evaluate_short(condition_, context);
        return std::nullopt;
    }
    return evaluate_normal(condition_, context);
}

void ResetWhenCondition::reset_state() {
    reset_all({condition_, reset_condition_});
}

ThenCondition::ThenCondition(
    std::vector<ConditionPtr> conditions,
    std::optional<std::chrono::nanoseconds> within
)
    : conditions_(std::move(conditions)), within_(within) {
    if (conditions_.empty()) {
        throw std::invalid_argument("then requires at least one condition");
    }
    if (within_.has_value() && within_->count() < 0) {
        throw std::invalid_argument("within must be non-negative");
    }
}

std::vector<const Condition*> ThenCondition::children() const {
    std::vector<const Condition*> result;
    result.reserve(conditions_.size());
    for (const auto& condition : conditions_) {
        result.push_back(condition.get());
    }
    return result;
}

std::string ThenCondition::describe() const {
    std::string result = "then " + std::to_string(conditions_.size());
    if (within_.has_value()) {
        result += " within " + format_duration(*within_);
    }
    return result;
}

std::optional<bool> ThenCondition::evaluate_impl(FrameContext& context, bool short_circuited) {
    if (completed_) {
        for (const auto& condition : conditions_) {
            condition->mark_skipped();
        }
        return short_circuited ? std::nullopt : std::optional<bool>{true};
    }
    if (started_at_.has_value()) {
        if (context.now() < *started_at_) {
            throw std::invalid_argument("monotonic time moved backwards");
        }
        const auto elapsed = (context.now() - *started_at_).count();
        if (within_.has_value() && elapsed > within_->count()) {
            index_ = 0;
            started_at_.reset();
        }
    }
    bool current = false;
    for (std::size_t step = 0; step < conditions_.size(); ++step) {
        if (step == index_) {
            current = evaluate_normal(conditions_[step], context);
        } else {
            conditions_[step]->mark_skipped();
        }
    }
    bool fired = false;
    if (current) {
        if (index_ == 0 && conditions_.size() > 1) {
            started_at_ = context.now();
        }
        ++index_;
        if (index_ == conditions_.size()) {
            completed_ = true;
            index_ = 0;
            started_at_.reset();
            fired = true;
        }
    }
    return short_circuited ? std::nullopt : std::optional<bool>{fired};
}

void ThenCondition::reset_state() {
    index_ = 0;
    started_at_.reset();
    completed_ = false;
    reset_all(conditions_);
}

}  // namespace divergencesplitter
