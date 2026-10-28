#pragma once

#include <opencv2/core.hpp>
#include <opencv2/imgproc.hpp>

#include <chrono>
#include <cstdint>
#include <deque>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "divergencesplitter/clock.hpp"
#include "divergencesplitter/frame.hpp"
#include "divergencesplitter/livesplit/bridge_client.hpp"

namespace divergencesplitter::test {

class ManualTimeProvider final : public TimeProvider {
public:
    [[nodiscard]] MonotonicTime now() const override { return value_; }
    void set(std::int64_t nanoseconds) { value_.nanoseconds = nanoseconds; }
    void advance(std::chrono::nanoseconds amount) { value_.nanoseconds += amount.count(); }

private:
    MonotonicTime value_{};
};

class FakeBridgeClient final : public BridgeClient {
public:
    explicit FakeBridgeClient(BridgeSnapshot initial) : current_(std::move(initial)) {}

    void wait_until_ready(std::chrono::milliseconds) override {}
    [[nodiscard]] bool is_ready() const override {
        std::scoped_lock lock{mutex_};
        return ready_;
    }
    [[nodiscard]] std::uint32_t session_id() const override {
        std::scoped_lock lock{mutex_};
        return current_.session_id;
    }
    [[nodiscard]] BridgeSnapshot synchronize() override {
        std::scoped_lock lock{mutex_};
        ++sync_count_;
        return current_;
    }
    [[nodiscard]] std::optional<BridgeEvent> next_event(std::chrono::milliseconds) override {
        std::scoped_lock lock{mutex_};
        if (events_.empty()) {
            return std::nullopt;
        }
        const auto event = events_.front();
        events_.pop_front();
        return event;
    }
    [[nodiscard]] std::uint64_t dropped_event_count() const override {
        std::scoped_lock lock{mutex_};
        return dropped_;
    }
    [[nodiscard]] BridgeControlResult execute(ActionOperation operation) override {
        {
            std::scoped_lock lock{mutex_};
            actions_.push_back(operation);
        }
        if (on_execute) {
            return on_execute(operation);
        }
        return BridgeControlResult{BridgeControlStatus::ok, {}};
    }
    void close() noexcept override {
        std::scoped_lock lock{mutex_};
        ready_ = false;
    }

    void set_snapshot(BridgeSnapshot snapshot) {
        std::scoped_lock lock{mutex_};
        current_ = std::move(snapshot);
    }
    [[nodiscard]] BridgeSnapshot snapshot() const {
        std::scoped_lock lock{mutex_};
        return current_;
    }
    [[nodiscard]] std::vector<ActionOperation> actions() const {
        std::scoped_lock lock{mutex_};
        return actions_;
    }
    void push_event(BridgeEvent event) {
        std::scoped_lock lock{mutex_};
        events_.push_back(std::move(event));
    }
    [[nodiscard]] std::uint64_t sync_count() const {
        std::scoped_lock lock{mutex_};
        return sync_count_;
    }
    void set_dropped(std::uint64_t value) {
        std::scoped_lock lock{mutex_};
        dropped_ = value;
    }
    void set_ready(bool value) {
        std::scoped_lock lock{mutex_};
        ready_ = value;
    }

    std::function<BridgeControlResult(ActionOperation)> on_execute;

private:
    mutable std::mutex mutex_;
    BridgeSnapshot current_;
    bool ready_{true};
    std::uint64_t sync_count_{};
    std::uint64_t dropped_{};
    std::deque<BridgeEvent> events_;
    std::vector<ActionOperation> actions_;
};

[[nodiscard]] cv::Mat solid(int width, int height, int gray);
[[nodiscard]] BridgeSnapshot make_snapshot(
    TimerPhase phase,
    std::int32_t split_index,
    std::int32_t split_count,
    std::uint64_t revision = 1,
    std::uint32_t session_id = 1
);
[[nodiscard]] FrameContext make_context(
    const cv::Mat& image,
    ManualTimeProvider& time
);

template <typename Predicate>
bool wait_until(Predicate predicate, std::chrono::milliseconds timeout = std::chrono::seconds{5}) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (std::chrono::steady_clock::now() < deadline) {
        if (predicate()) {
            return true;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds{5});
    }
    return predicate();
}

}  // namespace divergencesplitter::test
