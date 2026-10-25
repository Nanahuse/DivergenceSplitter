#pragma once

#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

#include "divergencesplitter/frame.hpp"
#include "divergencesplitter/livesplit/adapter.hpp"
#include "divergencesplitter/livesplit/bridge_client.hpp"
#include "divergencesplitter/runtime/logging.hpp"
#include "divergencesplitter/runtime/diagnostics.hpp"
#include "divergencesplitter/runtime/scenario_runtime.hpp"
#include "divergencesplitter/scenario/scenario.hpp"

namespace divergencesplitter {

struct InstanceRuntimeOptions {
    std::chrono::milliseconds reaction_time{0};
    std::chrono::milliseconds idle_wait{5};
    std::shared_ptr<Logger> logger;
};

class InstanceRuntime {
public:
    InstanceRuntime(
        int index,
        Scenario scenario,
        std::unique_ptr<BridgeClient> client,
        InstanceRuntimeOptions options = {}
    );
    ~InstanceRuntime();

    InstanceRuntime(const InstanceRuntime&) = delete;
    InstanceRuntime& operator=(const InstanceRuntime&) = delete;

    void start();
    void stop();
    void publish_frame(std::shared_ptr<SharedFrameEvaluation> shared);
    void request_manual_reset();

    [[nodiscard]] int index() const noexcept { return index_; }
    [[nodiscard]] InstanceState state() const;
    [[nodiscard]] InstanceDiagnosticsSnapshot diagnostics() const;

private:
    void run();
    void run_connected();
    void set_state(InstanceState state, std::string error = {});
    void apply_update(const LiveSplitUpdate& update);
    void dispatch_action(const Action& action, const FrameContext& context);
    void handle_manual_reset();
    [[nodiscard]] std::shared_ptr<SharedFrameEvaluation> take_frame();
    [[nodiscard]] bool wait_for_frame(std::chrono::milliseconds timeout);
    void set_runtime(std::shared_ptr<ScenarioRuntime> runtime);
    [[nodiscard]] std::shared_ptr<ScenarioRuntime> runtime() const;
    void record_action(const Action& action, std::string result);
    [[nodiscard]] bool stop_requested() const;
    void request_stop();

    int index_;
    Scenario scenario_;
    std::unique_ptr<BridgeClient> client_;
    InstanceRuntimeOptions options_;

    mutable std::mutex state_mutex_;
    InstanceState state_{InstanceState::connecting};
    std::string error_;
    std::optional<RunInfo> run_;
    std::uint64_t generation_{};
    std::uint64_t action_count_{};
    std::optional<ActionOperation> last_action_;
    std::string last_action_result_;

    mutable std::mutex runtime_mutex_;
    std::shared_ptr<ScenarioRuntime> runtime_;

    mutable std::mutex frame_mutex_;
    std::condition_variable frame_cv_;
    std::shared_ptr<SharedFrameEvaluation> pending_frame_;
    bool manual_reset_requested_{false};
    bool stop_requested_{false};
    bool running_{false};
    std::uint64_t last_dropped_count_{};
    std::optional<BridgeEventKind> pending_event_;
    struct UnknownControlGuard {
        ActionOperation operation;
        LiveSplitSnapshot snapshot;
    };
    std::optional<UnknownControlGuard> unknown_guard_;

    std::thread thread_;
    std::unique_ptr<LiveSplitBridgeAdapter> adapter_;
};

}  // namespace divergencesplitter
