#include "divergencesplitter/runtime/instance_runtime.hpp"

#include <algorithm>
#include <chrono>
#include <stdexcept>
#include <thread>

namespace divergencesplitter {

std::string_view to_string(TimerPhase phase) noexcept {
    switch (phase) {
        case TimerPhase::not_running:
            return "not_running";
        case TimerPhase::running:
            return "running";
        case TimerPhase::paused:
            return "paused";
        case TimerPhase::ended:
            return "ended";
        case TimerPhase::unspecified:
            return "unspecified";
    }
    return "unspecified";
}

std::string_view to_string(UpdateKind kind) noexcept {
    switch (kind) {
        case UpdateKind::initial:
            return "initial";
        case UpdateKind::resync:
            return "resync";
        case UpdateKind::periodic:
            return "periodic";
        case UpdateKind::transition:
            return "transition";
    }
    return "periodic";
}

std::string_view to_string(InstanceState state) noexcept {
    switch (state) {
        case InstanceState::connecting:
            return "connecting";
        case InstanceState::ready:
            return "ready";
        case InstanceState::failed:
            return "failed";
        case InstanceState::stopped:
            return "stopped";
    }
    return "unknown";
}

namespace {

bool fatal_bridge_error(BridgeErrorKind kind) {
    return kind == BridgeErrorKind::protocol_error ||
           kind == BridgeErrorKind::remote_error ||
           kind == BridgeErrorKind::internal_error;
}

bool transient_bridge_error(BridgeErrorKind kind) {
    return kind == BridgeErrorKind::timeout ||
           kind == BridgeErrorKind::not_ready ||
           kind == BridgeErrorKind::connection_lost ||
           kind == BridgeErrorKind::unstable_state ||
           kind == BridgeErrorKind::control_result_unknown;
}

}  // namespace

InstanceRuntime::InstanceRuntime(
    int index,
    Scenario scenario,
    std::unique_ptr<BridgeClient> client,
    InstanceRuntimeOptions options
)
    : index_(index),
      scenario_(std::move(scenario)),
      client_(std::move(client)),
      options_(options) {
    if (!client_) {
        throw std::invalid_argument("client must not be null");
    }
}

InstanceRuntime::~InstanceRuntime() {
    stop();
}

void InstanceRuntime::start() {
    {
        std::scoped_lock lock{frame_mutex_};
        if (running_) {
            return;
        }
        running_ = true;
        stop_requested_ = false;
    }
    set_state(InstanceState::connecting);
    thread_ = std::thread(&InstanceRuntime::run, this);
}

void InstanceRuntime::stop() {
    request_stop();
    if (thread_.joinable()) {
        thread_.join();
    }
    {
        std::scoped_lock lock{frame_mutex_};
        running_ = false;
    }
}

void InstanceRuntime::request_stop() {
    {
        std::scoped_lock lock{frame_mutex_};
        stop_requested_ = true;
    }
    frame_cv_.notify_all();
}

bool InstanceRuntime::stop_requested() const {
    std::scoped_lock lock{frame_mutex_};
    return stop_requested_;
}

void InstanceRuntime::publish_frame(std::shared_ptr<SharedFrameEvaluation> shared) {
    {
        std::scoped_lock lock{frame_mutex_};
        if (stop_requested_) {
            return;
        }
        pending_frame_ = std::move(shared);
    }
    frame_cv_.notify_all();
}

void InstanceRuntime::request_manual_reset() {
    {
        std::scoped_lock lock{frame_mutex_};
        if (stop_requested_) {
            return;
        }
        manual_reset_requested_ = true;
    }
    frame_cv_.notify_all();
}

std::shared_ptr<SharedFrameEvaluation> InstanceRuntime::take_frame() {
    std::scoped_lock lock{frame_mutex_};
    auto result = std::move(pending_frame_);
    pending_frame_.reset();
    return result;
}

bool InstanceRuntime::wait_for_frame(std::chrono::milliseconds timeout) {
    std::unique_lock lock{frame_mutex_};
    frame_cv_.wait_for(lock, timeout, [this]() {
        return pending_frame_ != nullptr || stop_requested_;
    });
    return pending_frame_ != nullptr;
}

void InstanceRuntime::set_state(InstanceState state, std::string error) {
    InstanceState previous = InstanceState::connecting;
    const std::string error_text = error;
    {
        std::scoped_lock lock{state_mutex_};
        previous = state_;
        state_ = state;
        error_ = std::move(error);
    }
    if (options_.logger && previous != state) {
        std::string message = "instance[" + std::to_string(index_) + "] " +
                              std::string{to_string(state)};
        if (!error_text.empty()) {
            message += ": " + error_text;
        }
        options_.logger->log(
            state == InstanceState::failed ? LogLevel::error : LogLevel::info,
            "instance.state",
            message
        );
    }
}

InstanceState InstanceRuntime::state() const {
    std::scoped_lock lock{state_mutex_};
    return state_;
}

void InstanceRuntime::set_runtime(std::shared_ptr<ScenarioRuntime> runtime) {
    std::scoped_lock lock{runtime_mutex_};
    runtime_ = std::move(runtime);
}

std::shared_ptr<ScenarioRuntime> InstanceRuntime::runtime() const {
    std::scoped_lock lock{runtime_mutex_};
    return runtime_;
}

InstanceDiagnosticsSnapshot InstanceRuntime::diagnostics() const {
    InstanceDiagnosticsSnapshot result;
    {
        std::scoped_lock lock{state_mutex_};
        result.index = index_;
        result.state = state_;
        result.error = error_;
        result.run = run_;
        result.generation = generation_;
        result.action_count = action_count_;
        result.last_action = last_action_;
        result.last_action_result = last_action_result_;
    }
    const auto current_runtime = runtime();
    if (current_runtime) {
        result.scenario = current_runtime->diagnostics();
    }
    return result;
}

void InstanceRuntime::run() {
    try {
        while (!stop_requested()) {
            if (!client_->is_ready()) {
                try {
                    client_->wait_until_ready(std::chrono::milliseconds{100});
                } catch (const BridgeError& error) {
                    if (fatal_bridge_error(error.kind())) {
                        set_state(InstanceState::failed, error.what());
                        break;
                    }
                    std::this_thread::sleep_for(std::chrono::milliseconds{50});
                    continue;
                }
                if (!client_->is_ready()) {
                    continue;
                }
            }

            try {
                adapter_ = std::make_unique<LiveSplitBridgeAdapter>(*client_);
                auto initial = adapter_->attach();
                auto scenario_runtime = std::make_shared<ScenarioRuntime>(scenario_);
                scenario_runtime->apply_update(initial);
                set_runtime(scenario_runtime);
                {
                    std::scoped_lock lock{state_mutex_};
                    run_ = initial.run_info;
                    error_.clear();
                    ++generation_;
                }
                last_dropped_count_ = client_->dropped_event_count();
                pending_event_.reset();
                {
                    std::scoped_lock lock{frame_mutex_};
                    manual_reset_requested_ = false;
                }
                if (options_.logger) {
        options_.logger->log(LogLevel::info, "instance.ready", "instance[" + std::to_string(index_) + "]");
    }
    set_state(InstanceState::ready);
                run_connected();
            } catch (const BridgeError& error) {
                set_runtime(nullptr);
                adapter_.reset();
                if (fatal_bridge_error(error.kind())) {
                    set_state(InstanceState::failed, error.what());
                    break;
                }
                if (error.kind() == BridgeErrorKind::closed) {
                    break;
                }
                if (transient_bridge_error(error.kind())) {
                    set_state(InstanceState::connecting, error.what());
                } else {
                    set_state(InstanceState::failed, error.what());
                    break;
                }
            } catch (const std::exception& error) {
                set_runtime(nullptr);
                adapter_.reset();
                set_state(InstanceState::failed, error.what());
                break;
            }

            if (!stop_requested()) {
                std::this_thread::sleep_for(std::chrono::milliseconds{50});
            }
        }
    } catch (const std::exception& error) {
        set_state(InstanceState::failed, error.what());
    }

    set_runtime(nullptr);
    adapter_.reset();
    {
        std::scoped_lock lock{state_mutex_};
        run_.reset();
    }
    client_->close();
    if (state() != InstanceState::failed) {
        set_state(InstanceState::stopped);
    }
}

void InstanceRuntime::run_connected() {
    auto scenario_runtime = runtime();
    if (!scenario_runtime) {
        return;
    }

    while (!stop_requested() && client_->is_ready()) {
        if (pending_event_.has_value()) {
            const auto event = *pending_event_;
            pending_event_.reset();
            auto update = adapter_->synchronize(event);
            apply_update(update);
        }

        const auto event = client_->next_event(std::chrono::milliseconds{0});
        if (event.has_value()) {
            auto update = adapter_->synchronize(*event);
            apply_update(update);
        }

        const auto dropped = client_->dropped_event_count();
        if (dropped > last_dropped_count_) {
            last_dropped_count_ = dropped;
            auto update = adapter_->synchronize(BridgeEventKind::run_changed);
            apply_update(update);
        }

        bool manual_reset = false;
        {
            std::scoped_lock lock{frame_mutex_};
            manual_reset = manual_reset_requested_;
            manual_reset_requested_ = false;
        }
        if (manual_reset) {
            handle_manual_reset();
        }

        if (stop_requested()) {
            return;
        }
        if (!wait_for_frame(options_.idle_wait)) {
            continue;
        }
        auto shared = take_frame();
        if (!shared) {
            continue;
        }
        auto current_runtime = runtime();
        if (!current_runtime) {
            continue;
        }
        FrameContext context{std::move(shared)};
        auto action = current_runtime->evaluate(context);
        if (action.has_value()) {
            dispatch_action(*action, context);
        }
    }

    if (!stop_requested() && !client_->is_ready()) {
        set_runtime(nullptr);
        adapter_.reset();
        set_state(InstanceState::connecting, "connection lost");
    }
}

void InstanceRuntime::apply_update(const LiveSplitUpdate& update) {
    auto current_runtime = runtime();
    if (current_runtime) {
        current_runtime->apply_update(update);
    }
    if (update.run_info.has_value()) {
        std::scoped_lock lock{state_mutex_};
        if (!run_.has_value() || !(*run_ == *update.run_info)) {
            run_ = *update.run_info;
        }
    }
}

void InstanceRuntime::dispatch_action(const Action& action, const FrameContext& context) {
    auto current_runtime = runtime();
    if (!current_runtime) {
        return;
    }
    const auto expected = current_runtime->current_snapshot();
    if (!expected.has_value()) {
        return;
    }

    if (options_.reaction_time.count() > 0) {
        const auto due = context.frame().captured_at + options_.reaction_time;
        while (true) {
            if (stop_requested()) {
                current_runtime->action_not_dispatched(action);
                record_action(action, "cancelled (stop)");
                return;
            }
            if (monotonic_now() >= due) {
                break;
            }
            if (auto pending = client_->next_event(std::chrono::milliseconds{0});
                pending.has_value()) {
                pending_event_ = *pending;
                current_runtime->action_not_dispatched(action);
                record_action(action, "cancelled (event)");
                return;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds{1});
        }
    }

    const auto current = current_runtime->current_snapshot();
    if (!current.has_value() || !(*current == *expected)) {
        current_runtime->action_not_dispatched(action);
        record_action(action, "not dispatched (state changed)");
        return;
    }
    if (unknown_guard_.has_value()) {
        if (unknown_guard_->operation != action.operation ||
            unknown_guard_->snapshot != *current) {
            unknown_guard_.reset();
        } else {
            current_runtime->action_not_dispatched(action);
            record_action(action, "suppressed (unknown control outcome)");
            return;
        }
    }

    const auto result = client_->execute(action.operation);
    switch (result.status) {
        case BridgeControlStatus::ok: {
            record_action(action, "ok");
            auto update = adapter_->synchronize_after_control();
            apply_update(update);
            return;
        }
        case BridgeControlStatus::unknown:
            record_action(action, "unknown");
            unknown_guard_ = UnknownControlGuard{action.operation, *expected};
            throw BridgeError(
                BridgeErrorKind::control_result_unknown,
                result.message.empty() ? "control result unknown" : result.message
            );
        case BridgeControlStatus::connection_lost:
            current_runtime->action_not_dispatched(action);
            record_action(action, "connection lost");
            throw BridgeError(
                BridgeErrorKind::connection_lost,
                result.message.empty() ? "connection lost" : result.message
            );
        case BridgeControlStatus::error:
            current_runtime->action_not_dispatched(action);
            record_action(action, result.message.empty() ? "error" : result.message);
            return;
    }
}

void InstanceRuntime::handle_manual_reset() {
    auto current_runtime = runtime();
    if (!current_runtime) {
        return;
    }
    const auto expected = current_runtime->current_snapshot();
    if (!expected.has_value()) {
        return;
    }
    if (expected->phase != TimerPhase::running &&
        expected->phase != TimerPhase::paused &&
        expected->phase != TimerPhase::ended) {
        return;
    }
    const auto result = client_->execute(ActionOperation::reset);
    if (result.status == BridgeControlStatus::ok) {
        record_action(Action{ActionOperation::reset}, "ok (manual)");
        auto update = adapter_->synchronize_after_control();
        apply_update(update);
        return;
    }
    if (result.status == BridgeControlStatus::unknown) {
        record_action(Action{ActionOperation::reset}, "unknown (manual)");
        throw BridgeError(
            BridgeErrorKind::control_result_unknown,
            result.message.empty() ? "manual reset result unknown" : result.message
        );
    }
    if (result.status == BridgeControlStatus::connection_lost) {
        record_action(Action{ActionOperation::reset}, "connection lost (manual)");
        throw BridgeError(
            BridgeErrorKind::connection_lost,
            result.message.empty() ? "connection lost" : result.message
        );
    }
    record_action(Action{ActionOperation::reset}, result.message.empty() ? "error (manual)" : result.message);
}

void InstanceRuntime::record_action(const Action& action, std::string result) {
    {
        std::scoped_lock lock{state_mutex_};
        last_action_ = action.operation;
        last_action_result_ = result;
        ++action_count_;
    }
    if (options_.logger) {
        options_.logger->log(
            LogLevel::info,
            "instance.action",
            "instance[" + std::to_string(index_) + "] " +
                std::string{to_string(action.operation)} + " -> " + result
        );
    }
}

}  // namespace divergencesplitter
