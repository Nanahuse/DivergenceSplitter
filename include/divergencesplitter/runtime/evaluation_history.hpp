#pragma once

#include <cstdint>
#include <deque>
#include <memory>
#include <optional>
#include <string>
#include <vector>
#include <unordered_set>

#include "divergencesplitter/condition/condition.hpp"

namespace divergencesplitter {

using HistoryPaths = std::unordered_set<std::string>;

enum class HistoryEvent { sample, gap, reset, transition, error };

struct EvaluationSample {
    MonotonicTime time;
    std::optional<double> value;
    ConditionStatus status{ConditionStatus::not_evaluated};
    HistoryEvent event{HistoryEvent::sample};
    std::optional<bool> result;
};

struct ConditionMeasurement {
    std::optional<double> value;
    std::optional<double> target;
    std::string unit;
    bool stairs{};
};

[[nodiscard]] ConditionMeasurement condition_measurement(const Condition& condition);

struct ConditionHistory {
    std::string path;
    std::vector<EvaluationSample> samples;
};

struct EvaluationHistorySnapshot {
    std::uint64_t identity{}; // Unique across reconnects, profile applies and Bridge sessions.
    MonotonicTime sampled_at;
    std::vector<ConditionHistory> conditions;
};

// Called only under ScenarioRuntime's mutex. Snapshot copies are opt-in (10 Hz UI).
class EvaluationHistory : public std::enable_shared_from_this<EvaluationHistory> {
public:
    static constexpr std::size_t capacity = 8192;
    explicit EvaluationHistory(std::shared_ptr<TimeProvider> clock = {});
    void bind(const Condition* condition, const std::string& path);
    void begin_frame(MonotonicTime time);
    void end_frame();
    void clear();
    [[nodiscard]] std::shared_ptr<const EvaluationHistorySnapshot> snapshot(const HistoryPaths* paths = nullptr) const;

private:
    // Collection and retention keep the original bounded deque. UI snapshots are
    // contiguous so dense lists do not allocate one MSVC deque block per sample.
    struct Buffer {
        std::string path;
        std::deque<EvaluationSample> samples;
    };
    struct Series {
        Buffer history;
        std::uint64_t frame{};
    };
    void record(std::size_t index, const Condition& condition, Condition::Observation event,
                std::optional<bool> result, std::optional<MonotonicTime> time, bool short_circuited);
    void append(Series& series, EvaluationSample sample);
    std::vector<Series> series_;
    std::shared_ptr<TimeProvider> clock_;
    std::uint64_t identity_{};
    std::uint64_t frame_{};
    std::optional<MonotonicTime> frame_time_;
};

} // namespace divergencesplitter
