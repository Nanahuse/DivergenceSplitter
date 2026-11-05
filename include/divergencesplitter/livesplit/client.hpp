#pragma once

#include <chrono>
#include <cstdint>
#include <memory>
#include <string>

#include "divergencesplitter/livesplit/bridge_client.hpp"

namespace divergencesplitter {

struct LiveSplitClientOptions {
    std::string host{"127.0.0.1"};
    std::uint16_t port{54000};
    std::chrono::milliseconds connect_timeout{3000};
    std::chrono::milliseconds response_timeout{3000};
    std::chrono::milliseconds ready_timeout{10000};
    std::chrono::milliseconds sync_timeout{10000};
};

class LiveSplitBridgeClient final : public BridgeClient {
public:
    explicit LiveSplitBridgeClient(LiveSplitClientOptions options);
    ~LiveSplitBridgeClient() override;

    LiveSplitBridgeClient(const LiveSplitBridgeClient&) = delete;
    LiveSplitBridgeClient& operator=(const LiveSplitBridgeClient&) = delete;

    void wait_until_ready(std::chrono::milliseconds timeout) override;
    [[nodiscard]] bool is_ready() const override;
    [[nodiscard]] std::uint32_t session_id() const override;
    [[nodiscard]] BridgeSnapshot synchronize() override;
    [[nodiscard]] std::optional<BridgeEvent> next_event(
        std::chrono::milliseconds timeout
    ) override;
    [[nodiscard]] std::uint64_t dropped_event_count() const override;
    [[nodiscard]] BridgeControlResult execute(ActionOperation operation) override;
    void close() noexcept override;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace divergencesplitter
