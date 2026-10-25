#pragma once

#include <chrono>
#include <cstdint>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "divergencesplitter/rule/rule.hpp"
#include "divergencesplitter/runtime/models.hpp"

namespace divergencesplitter {

enum class BridgeErrorKind {
    closed,
    timeout,
    not_ready,
    connection_lost,
    protocol_error,
    remote_error,
    control_result_unknown,
    unstable_state,
    internal_error,
};

[[nodiscard]] std::string_view to_string(BridgeErrorKind kind) noexcept;

class BridgeError : public std::runtime_error {
public:
    BridgeError(BridgeErrorKind kind, std::string message)
        : std::runtime_error(std::move(message)), kind_(kind) {}

    [[nodiscard]] BridgeErrorKind kind() const noexcept { return kind_; }

private:
    BridgeErrorKind kind_;
};

struct BridgeSnapshot {
    std::uint32_t session_id{};
    TimerPhase phase{TimerPhase::not_running};
    std::int32_t split_index{-1};
    std::int32_t split_count{};
    std::vector<std::string> segment_names;
    std::string game_name;
    std::string category_name;
};

enum class BridgeEventKind {
    timer,
    reset,
    run_changed,
    context_changed,
    other,
};

enum class BridgeControlStatus {
    ok,
    unknown,
    connection_lost,
    error,
};

struct BridgeControlResult {
    BridgeControlStatus status{BridgeControlStatus::ok};
    std::string message;

    [[nodiscard]] bool ok() const noexcept { return status == BridgeControlStatus::ok; }
};

class BridgeClient {
public:
    virtual ~BridgeClient() = default;

    virtual void wait_until_ready(std::chrono::milliseconds timeout) = 0;
    [[nodiscard]] virtual bool is_ready() const = 0;
    [[nodiscard]] virtual std::uint32_t session_id() const = 0;
    [[nodiscard]] virtual BridgeSnapshot synchronize() = 0;
    [[nodiscard]] virtual std::optional<BridgeEventKind> next_event(
        std::chrono::milliseconds timeout
    ) = 0;
    [[nodiscard]] virtual std::uint64_t dropped_event_count() const = 0;
    [[nodiscard]] virtual BridgeControlResult execute(ActionOperation operation) = 0;
    virtual void close() noexcept = 0;
};

}  // namespace divergencesplitter
