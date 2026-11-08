#include "divergencesplitter/runtime/evaluation_history.hpp"

#include <algorithm>
#include <atomic>
#include <cmath>

#include "divergencesplitter/condition/conditions.hpp"

namespace divergencesplitter {
namespace {
std::atomic<std::uint64_t> next_identity{1};
}

ConditionMeasurement condition_measurement(const Condition& condition) {
    if (const auto* value = dynamic_cast<const DetectedCondition*>(&condition))
        return {value->latest_score(), value->minimum_score(), "score", false};
    if (const auto* value = dynamic_cast<const HoldCondition*>(&condition))
        return {value->elapsed_nanoseconds().transform([](auto ns) { return ns / 1e9; }),
                value->duration().count() / 1e9, "s", false};
    if (const auto* value = dynamic_cast<const ElapsedCondition*>(&condition))
        return {value->elapsed_nanoseconds().transform([](auto ns) { return ns / 1e9; }),
                value->duration().count() / 1e9, "s", false};
    if (const auto* value = dynamic_cast<const NthCondition*>(&condition))
        return {static_cast<double>(value->observed()), static_cast<double>(value->count()), "count", true};
    if (const auto* value = dynamic_cast<const OnceCondition*>(&condition))
        return {value->completed() ? 1.0 : 0.0, 1.0, "completed", true};
    if (const auto* value = dynamic_cast<const ThenCondition*>(&condition))
        return {static_cast<double>(value->completed() ? value->step_count() : value->current_step()), static_cast<double>(value->step_count()), "step", true};
    return {{}, {}, "state", true};
}

EvaluationHistory::EvaluationHistory(std::shared_ptr<TimeProvider> clock)
    : clock_(clock ? std::move(clock) : std::make_shared<SteadyTimeProvider>()),
      identity_(next_identity.fetch_add(1)) {}

void EvaluationHistory::bind(const Condition* condition, const std::string& path) {
    if (!condition) return;
    const auto index = series_.size();
    series_.push_back({{path, {}}, 0});
    condition->set_observer([weak = weak_from_this(), index](const Condition& node,
        Condition::Observation event, std::optional<bool> result,
        std::optional<MonotonicTime> time, bool short_circuited) {
        if (const auto history = weak.lock())
            history->record(index, node, event, result, time, short_circuited);
    });
    const auto children = condition->children();
    for (std::size_t child = 0; child < children.size(); ++child)
        bind(children[child], path + ".c" + std::to_string(child));
}

void EvaluationHistory::begin_frame(MonotonicTime time) {
    frame_time_ = time;
    ++frame_;
}

void EvaluationHistory::end_frame() {
    for (auto& series : series_) {
        if (series.frame != frame_ && !series.history.samples.empty()) {
            try {
                append(series, {*frame_time_, {}, ConditionStatus::skipped, HistoryEvent::gap, {}});
            } catch (...) {} // Diagnostics allocation failures cannot affect a decision.
        }
    }
    frame_time_.reset();
}

void EvaluationHistory::record(std::size_t index, const Condition& condition,
    Condition::Observation event, std::optional<bool> result,
    std::optional<MonotonicTime> time, bool short_circuited) {
    auto& series = series_[index];
    series.frame = frame_;
    EvaluationSample sample{time ? *time : (frame_time_ ? *frame_time_ : clock_->now()), {},
                            condition.status(), HistoryEvent::sample, result};
    if (event == Condition::Observation::reset) {
        sample.event = HistoryEvent::reset;
    } else if (event == Condition::Observation::error) {
        sample.event = HistoryEvent::error;
    } else if (event == Condition::Observation::skipped ||
               (short_circuited && condition.type_name() == "detected")) {
        sample.event = HistoryEvent::gap;
    } else {
        sample.value = condition_measurement(condition).value;
        if (!sample.value && result) sample.value = *result ? 1.0 : 0.0;
        if (!sample.value) sample.event = HistoryEvent::gap;
        const auto& samples = series.history.samples;
        if (sample.value && !samples.empty() && samples.back().value &&
            (condition.type_name() == "then" || condition.type_name() == "nth" ||
             condition.type_name() == "once" ||
             (condition.type_name() == "hold" && *sample.value < *samples.back().value)) &&
            sample.value != samples.back().value)
            sample.event = HistoryEvent::transition;
    }
    append(series, sample);
}

void EvaluationHistory::append(Series& series, EvaluationSample sample) {
    auto& samples = series.history.samples;
    const auto cutoff = sample.time - std::chrono::seconds{60};
    while (!samples.empty() && samples.front().time < cutoff) samples.pop_front();
    if (sample.event == HistoryEvent::gap && !samples.empty() &&
        samples.back().event == HistoryEvent::gap) return;
    if (samples.size() == capacity) {
        // Thin flat interiors first; preserve extrema, status changes and boundaries.
        std::deque<EvaluationSample> compact;
        compact.push_back(samples.front());
        for (std::size_t i = 1; i + 1 < samples.size(); ++i) {
            const auto& previous = samples[i - 1];
            const auto& current = samples[i];
            const auto& next = samples[i + 1];
            const bool extremum = current.value && previous.value && next.value &&
                ((*current.value > *previous.value && *current.value > *next.value) ||
                 (*current.value < *previous.value && *current.value < *next.value));
            if (i % 2 == 0 || current.event != HistoryEvent::sample ||
                current.status != previous.status || current.status != next.status || extremum)
                compact.push_back(current);
        }
        compact.push_back(samples.back());
        // An event storm is bounded too; prefer its most recent events.
        while (compact.size() > capacity * 3 / 4) compact.pop_front();
        samples.swap(compact);
    }
    samples.push_back(sample);
}

void EvaluationHistory::clear() {
    identity_ = next_identity.fetch_add(1);
    for (auto& series : series_) series.history.samples.clear();
}

std::shared_ptr<const EvaluationHistorySnapshot> EvaluationHistory::snapshot() const {
    auto result = std::make_shared<EvaluationHistorySnapshot>();
    result->identity = identity_;
    result->sampled_at = clock_->now();
    for (const auto& series : series_) {
        auto& target = result->conditions.emplace_back();
        target.path = series.history.path;
        for (const auto& sample : series.history.samples)
            if (sample.time >= result->sampled_at - std::chrono::seconds{60})
                target.samples.push_back(sample);
    }
    return result;
}
} // namespace divergencesplitter
