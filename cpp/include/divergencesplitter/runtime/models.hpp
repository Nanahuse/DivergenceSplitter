#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace divergencesplitter {

enum class TimerPhase {
    not_running,
    running,
    paused,
    ended,
    unspecified,
};

[[nodiscard]] std::string_view to_string(TimerPhase phase) noexcept;

enum class UpdateKind {
    initial,
    resync,
    periodic,
    transition,
};

[[nodiscard]] std::string_view to_string(UpdateKind kind) noexcept;

struct SegmentInfo {
    int index{};
    std::string name;

    friend bool operator==(const SegmentInfo&, const SegmentInfo&) = default;
};

struct RunInfo {
    std::uint32_t session_id{};
    std::uint64_t run_revision{};
    std::vector<SegmentInfo> segments;

    friend bool operator==(const RunInfo&, const RunInfo&) = default;
};

struct LiveSplitSnapshot {
    std::uint32_t session_id{};
    std::uint64_t state_revision{};
    std::uint64_t run_revision{};
    TimerPhase phase{TimerPhase::not_running};
    std::int32_t split_index{-1};
    std::int32_t split_count{};

    friend bool operator==(const LiveSplitSnapshot&, const LiveSplitSnapshot&) = default;
};

struct LiveSplitUpdate {
    UpdateKind kind{UpdateKind::periodic};
    LiveSplitSnapshot snapshot;
    std::optional<RunInfo> run_info;
};

}  // namespace divergencesplitter
