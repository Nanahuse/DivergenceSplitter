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

bool same_control_state(const LiveSplitSnapshot& left, const LiveSplitSnapshot& right) {
    return left.session_id == right.session_id && left.run_revision == right.run_revision &&
           left.phase == right.phase && left.split_index == right.split_index &&
           left.split_count == right.split_count;
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
        return pending_frame_ != nullptr || manual_reset_requested_ || stop_requested_;
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
                scheduled_action_.reset();
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

    scheduled_action_.reset();
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
        // Process queued state before controls; unrelated events leave the
        // reaction wait intact. Bound each batch so Stop/Reset stay responsive.
        bool events_drained = false;
        for (int count = 0; count < 64 && !stop_requested(); ++count) {
            const auto event = client_->next_event(std::chrono::milliseconds{0});
            if (!event.has_value()) {
                events_drained = true;
                break;
            }
            if (auto update = adapter_->apply_event(*event); update.has_value()) {
                apply_update(*update);
            }
        }
        if (!events_drained) {
            if (take_manual_reset_request()) {
                handle_manual_reset();
            }
            // Do not Query or send a normal control ahead of queued Events.
            continue;
        }

        const auto dropped = client_->dropped_event_count();
        if (dropped > last_dropped_count_) {
            last_dropped_count_ = dropped;
            auto update = adapter_->synchronize(BridgeEventKind::run_changed);
            apply_update(update);
        }

        const auto deadline = scenario_runtime->state_wait_deadline();
        if (deadline.has_value() && monotonic_now() >= *deadline) {
            // Query only on an expired confirmation wait, including when no
            // frames arrive. A missing event must not cause a duplicate control.
            apply_update(adapter_->synchronize(BridgeEventKind::other));
            scenario_runtime->state_wait_timed_out(monotonic_now());
        }

        if (scheduled_action_.has_value()) {
            const auto current = scenario_runtime->current_snapshot();
            if (!scenario_runtime->action_pending(scheduled_action_->action) ||
                !current.has_value() || !same_control_state(*current, scheduled_action_->expected)) {
                cancel_scheduled_action("cancelled (state changed)");
            }
        }

        if (take_manual_reset_request()) {
            handle_manual_reset();
        }

        if (stop_requested() || !client_->is_ready()) {
            break;
        }
        auto shared = take_frame();
        if (shared) {
            FrameContext context{std::move(shared)};
            auto action = scenario_runtime->evaluate(context);
            if (action.has_value()) {
                const bool reset_interrupts_reaction = action->operation == ActionOperation::reset &&
                    scheduled_action_.has_value() &&
                    scheduled_action_->action.operation != ActionOperation::reset;
                if (scheduled_action_.has_value()) {
                    cancel_scheduled_action("cancelled (reset priority)");
                }
                scheduled_action_ = ScheduledAction{
                    *action, *scenario_runtime->current_snapshot(),
                    reset_interrupts_reaction ? monotonic_now()
                                              : context.frame().captured_at + options_.reaction_time,
                };
                // Revisit Events and manual Reset before sending a newly
                // decided action, even when evaluation used the entire delay.
                continue;
            }
        }
        if (take_manual_reset_request()) {
            handle_manual_reset();
        }
        if (scheduled_action_.has_value() && monotonic_now() >= scheduled_action_->due) {
            const auto action = scheduled_action_->action;
            scheduled_action_.reset();
            dispatch_action(action);
        }
        (void)wait_for_frame(options_.idle_wait);
    }

    cancel_scheduled_action("cancelled (stop or disconnect)");
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

void InstanceRuntime::cancel_scheduled_action(std::string reason) {
    if (!scheduled_action_.has_value()) {
        return;
    }
    const auto action = scheduled_action_->action;
    scheduled_action_.reset();
    if (auto current_runtime = runtime()) {
        current_runtime->action_not_dispatched(action);
    }
    record_action(action, std::move(reason));
}

void InstanceRuntime::dispatch_action(const Action& action) {
    auto current_runtime = runtime();
    if (!current_runtime) {
        return;
    }
    const auto expected = current_runtime->current_snapshot();
    if (!expected.has_value() || !current_runtime->action_pending(action)) {
        return;
    }

    if (stop_requested() || !client_->is_ready()) {
        current_runtime->action_not_dispatched(action);
        record_action(action, "cancelled (stop or disconnect)");
        return;
    }
    if (unknown_guard_.has_value()) {
        if (unknown_guard_->operation != action.operation ||
            !same_control_state(unknown_guard_->snapshot, *expected)) {
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
            current_runtime->action_accepted(action, monotonic_now());
            record_action(action, "ok");
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
            if (action.operation != ActionOperation::reset) {
                current_runtime->action_not_dispatched(action);
            }
            record_action(action, result.message.empty() ? "error" : result.message);
            if (action.operation == ActionOperation::reset) {
                // A rejected Reset can race a completed Split or an external
                // timer change. Query before releasing either confirmation wait.
                // Query failure follows the normal reconnect path without
                // evaluating another frame against an unconfirmed snapshot.
                const auto update = adapter_->synchronize(BridgeEventKind::other);
                current_runtime->settle_rejected_reset(update);
                apply_update(update);
            }
            return;
    }
}

void InstanceRuntime::handle_manual_reset() {
    auto current_runtime = runtime();
    if (!current_runtime) {
        return;
    }
    // An explicit Reset also cancels an automatic Reset's reaction wait.
    cancel_scheduled_action("cancelled (manual reset)");
    if (auto action = current_runtime->request_reset()) {
        dispatch_action(*action);
    }
}

bool InstanceRuntime::take_manual_reset_request() {
    std::scoped_lock lock{frame_mutex_};
    const bool requested = manual_reset_requested_;
    manual_reset_requested_ = false;
    return requested;
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
