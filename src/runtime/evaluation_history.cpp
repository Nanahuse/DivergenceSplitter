#include "divergencesplitter/runtime/evaluation_history.hpp"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <iterator>

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
    while (!samples.empty() && samples.front().time < cutoff) {
        samples.pop_front();
        ++series.first_index;
    }
    while (!series.preview_index.empty() && series.preview_index.front().last < series.first_index)
        series.preview_index.pop_front();
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
        series.preview_index.clear();
        series.first_index = 0;
        series.preview_valid = true;
        for (std::size_t i = 0; i < samples.size() && series.preview_valid; ++i) index_sample(series, i);
    }
    if (!samples.empty() && sample.time < samples.back().time) series.ordered = false;
    samples.push_back(sample);
    if (series.preview_valid) index_sample(series, samples.size() - 1);
    if ((sample.value || sample.result || sample.event == HistoryEvent::error) &&
        (!series.last_observation || sample.time > *series.last_observation))
        series.last_observation = sample.time;
}

void EvaluationHistory::index_sample(Series& series, std::size_t position) noexcept {
    // Index only stretches of ordinary, finite samples with the same state.
    // Events and missing values always occupy their own block.
    constexpr std::size_t block_size = 64;
    const auto& samples = series.history.samples;
    const auto& sample = samples[position];
    const auto ordinal = series.first_index + position;
    auto& index = series.preview_index;
    if (position > 0 && !index.empty()) {
        auto& block = index.back();
        const auto& previous = samples[position - 1];
        if (block.first >= series.first_index && ordinal - block.first < block_size &&
            sample.event == HistoryEvent::sample && previous.event == HistoryEvent::sample &&
            sample.status == previous.status && sample.result == previous.result &&
            history_preview_bucket(sample.time) == history_preview_bucket(previous.time) &&
            sample.time >= previous.time && sample.value && std::isfinite(*sample.value) &&
            previous.value && std::isfinite(*previous.value)) {
            if (*sample.value < *samples[block.low - series.first_index].value) block.low = ordinal;
            if (*sample.value >= *samples[block.high - series.first_index].value) block.high = ordinal;
            block.last = ordinal;
            return;
        }
    }
    try {
        index.push_back({ordinal, ordinal, ordinal, ordinal});
    } catch (...) {
        index.clear();
        series.preview_valid = false;
    }
}

void EvaluationHistory::clear() {
    identity_ = next_identity.fetch_add(1);
    for (auto& series : series_) {
        series.history.samples.clear();
        series.last_observation.reset();
        series.ordered = true;
        series.preview_index.clear();
        series.first_index = 0;
        series.preview_valid = true;
    }
    timer_resets_.clear();
}

void EvaluationHistory::note_timer_reset() noexcept {
    try {
        const auto now = clock_->now();
        while (!timer_resets_.empty() &&
               (timer_resets_.front() < now - std::chrono::seconds{60} || timer_resets_.size() >= capacity))
            timer_resets_.pop_front();
        timer_resets_.push_back(now);
    } catch (...) {} // Diagnostics must not affect a timer update.
}

std::shared_ptr<const EvaluationHistorySnapshot> EvaluationHistory::snapshot(const HistoryPaths* paths,
    std::chrono::seconds recent_window) const {
    auto result = std::make_shared<EvaluationHistorySnapshot>();
    result->identity = identity_;
    result->sampled_at = clock_->now();
    const auto retention = std::chrono::seconds{60};
    const auto cutoff = result->sampled_at - retention;
    const auto recent_cutoff = result->sampled_at - std::min(recent_window, retention);
    const auto preview_start = std::max(cutoff, history_preview_start(recent_cutoff));
    const bool recent_only = recent_window > std::chrono::seconds::zero();
    for (const auto time : timer_resets_)
        if (time >= (recent_only ? recent_cutoff : cutoff)) result->timer_resets.push_back(time);
    const auto requested = [&](const Series& series) {
        return paths ? paths->contains(series.history.path) : !recent_only;
    };
    const auto recent = [&](const Series& series) {
        const auto& samples = series.history.samples;
        return recent_only && !samples.empty() && series.last_observation &&
            *series.last_observation >= recent_cutoff &&
            (!series.ordered || *series.last_observation >= samples.front().time);
    };
    for (const auto& series : series_) {
        const auto& samples = series.history.samples;
        const bool full = requested(series);
        const bool in_window = recent(series);
        if (!full && !in_window) continue;
        auto& target = result->conditions.emplace_back();
        target.path = series.history.path;
        target.last_observation = series.last_observation;
        if (in_window && series.preview_valid) {
            auto& preview = full ? target.preview_samples.emplace() : target.samples;
            preview.reserve(std::min(samples.size(), series.preview_index.size() * 4));
            for (const auto& block : series.preview_index) {
                const auto last = block.last - series.first_index;
                if (samples[last].time < preview_start) continue;
                const auto first = std::max(block.first, series.first_index) - series.first_index;
                if (block.first < series.first_index || samples[first].time < preview_start) {
                    // Copy a clipped edge block exactly so a stale extremum cannot
                    // hide the first visible sample or leak across the window.
                    for (auto i = first; i <= last; ++i)
                        if (samples[i].time >= preview_start) preview.push_back(samples[i]);
                    continue;
                }
                const auto [earlier, later] = std::minmax(block.low, block.high);
                preview.push_back(samples[first]);
                if (earlier > block.first && earlier < block.last)
                    preview.push_back(samples[earlier - series.first_index]);
                if (later != earlier && later > block.first && later < block.last)
                    preview.push_back(samples[later - series.first_index]);
                if (last != first) preview.push_back(samples[last]);
            }
            if (!full) continue;
        }
        const auto since = full ? cutoff : preview_start;
        if (series.ordered) {
            const auto first = std::lower_bound(samples.begin(), samples.end(), since,
                [](const EvaluationSample& sample, MonotonicTime time) { return sample.time < time; });
            target.samples.assign(first, samples.end());
        } else {
            // A queued frame can predate a timer update that reset the condition.
            std::ranges::copy_if(samples, std::back_inserter(target.samples),
                [since](const auto& sample) { return sample.time >= since; });
        }
    }
    return result;
}
} // namespace divergencesplitter
