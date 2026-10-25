#include "divergencesplitter/livesplit/client.hpp"

#include <livesplit/bridge/client.hpp>

#include <chrono>
#include <memory>
#include <string>
#include <type_traits>
#include <variant>

namespace divergencesplitter {
namespace {

BridgeErrorKind map_error_kind(livesplit::bridge::error_kind kind) {
    using enum livesplit::bridge::error_kind;
    switch (kind) {
        case closed:
            return BridgeErrorKind::closed;
        case timeout:
            return BridgeErrorKind::timeout;
        case not_ready:
            return BridgeErrorKind::not_ready;
        case connection_lost:
            return BridgeErrorKind::connection_lost;
        case protocol_error:
            return BridgeErrorKind::protocol_error;
        case remote_error:
            return BridgeErrorKind::remote_error;
        case control_result_unknown:
            return BridgeErrorKind::control_result_unknown;
        case unstable_state:
            return BridgeErrorKind::unstable_state;
        case internal_error:
            return BridgeErrorKind::internal_error;
    }
    return BridgeErrorKind::internal_error;
}

[[noreturn]] void translate_error(const livesplit::bridge::error& error) {
    throw BridgeError(map_error_kind(error.kind()), error.what());
}

TimerPhase map_phase(livesplit::bridge::timer_phase phase) {
    using enum livesplit::bridge::timer_phase;
    switch (phase) {
        case NOT_RUNNING:
            return TimerPhase::not_running;
        case RUNNING:
            return TimerPhase::running;
        case PAUSED:
            return TimerPhase::paused;
        case ENDED:
            return TimerPhase::ended;
        case UNSPECIFIED:
            return TimerPhase::unspecified;
    }
    return TimerPhase::unspecified;
}

BridgeSnapshot map_snapshot(const livesplit::bridge::snapshot& snapshot) {
    BridgeSnapshot result;
    result.session_id = snapshot.session_id;
    result.phase = map_phase(snapshot.timer.phase);
    result.split_index = snapshot.timer.split_index;
    result.split_count = static_cast<std::int32_t>(snapshot.run.segments.size());
    result.segment_names.reserve(snapshot.run.segments.size());
    for (const auto& segment : snapshot.run.segments) {
        result.segment_names.push_back(segment.name);
    }
    result.game_name = snapshot.run.game_name;
    result.category_name = snapshot.run.category_name;
    return result;
}

}  // namespace

std::string_view to_string(BridgeErrorKind kind) noexcept {
    switch (kind) {
        case BridgeErrorKind::closed:
            return "closed";
        case BridgeErrorKind::timeout:
            return "timeout";
        case BridgeErrorKind::not_ready:
            return "not_ready";
        case BridgeErrorKind::connection_lost:
            return "connection_lost";
        case BridgeErrorKind::protocol_error:
            return "protocol_error";
        case BridgeErrorKind::remote_error:
            return "remote_error";
        case BridgeErrorKind::control_result_unknown:
            return "control_result_unknown";
        case BridgeErrorKind::unstable_state:
            return "unstable_state";
        case BridgeErrorKind::internal_error:
            return "internal_error";
    }
    return "unknown";
}

struct LiveSplitBridgeClient::Impl {
    explicit Impl(LiveSplitClientOptions options) {
        livesplit::bridge::client_options bridge_options;
        bridge_options.host = options.host;
        bridge_options.port = options.port;
        bridge_options.connect_timeout = options.connect_timeout;
        bridge_options.response_timeout = options.response_timeout;
        bridge_options.ready_timeout = options.ready_timeout;
        bridge_options.sync_timeout = options.sync_timeout;
        client = std::make_unique<livesplit::bridge::client>(std::move(bridge_options));
    }

    std::unique_ptr<livesplit::bridge::client> client;
};

LiveSplitBridgeClient::LiveSplitBridgeClient(LiveSplitClientOptions options)
    : impl_(std::make_unique<Impl>(std::move(options))) {}

LiveSplitBridgeClient::~LiveSplitBridgeClient() {
    close();
}

void LiveSplitBridgeClient::wait_until_ready(std::chrono::milliseconds timeout) {
    try {
        impl_->client->wait_until_ready(timeout);
    } catch (const livesplit::bridge::error& error) {
        translate_error(error);
    }
}

bool LiveSplitBridgeClient::is_ready() const {
    return impl_->client->is_ready();
}

std::uint32_t LiveSplitBridgeClient::session_id() const {
    return impl_->client->session_id();
}

BridgeSnapshot LiveSplitBridgeClient::synchronize() {
    try {
        return map_snapshot(impl_->client->synchronize());
    } catch (const livesplit::bridge::error& error) {
        translate_error(error);
    }
}

std::optional<BridgeEventKind> LiveSplitBridgeClient::next_event(
    std::chrono::milliseconds timeout
) {
    try {
        const auto event = impl_->client->next_event(timeout);
        if (!event.has_value()) {
            return std::nullopt;
        }
        return std::visit(
            [](const auto& value) -> BridgeEventKind {
                using Value = std::decay_t<decltype(value)>;
                if constexpr (std::is_same_v<Value, livesplit::bridge::timer_event>) {
                    return BridgeEventKind::timer;
                } else if constexpr (std::is_same_v<Value, livesplit::bridge::reset_event>) {
                    return BridgeEventKind::reset;
                } else if constexpr (std::is_same_v<Value, livesplit::bridge::changed_event>) {
                    using enum livesplit::bridge::changed_event_type;
                    switch (value.type) {
                        case RUN_CHANGED:
                            return BridgeEventKind::run_changed;
                        case CONTEXT_CHANGED:
                            return BridgeEventKind::context_changed;
                    }
                    return BridgeEventKind::other;
                } else {
                    return BridgeEventKind::other;
                }
            },
            *event
        );
    } catch (const livesplit::bridge::error& error) {
        translate_error(error);
    }
}

std::uint64_t LiveSplitBridgeClient::dropped_event_count() const {
    return impl_->client->dropped_event_count();
}

BridgeControlResult LiveSplitBridgeClient::execute(ActionOperation operation) {
    try {
        switch (operation) {
            case ActionOperation::start:
                impl_->client->start_async().get();
                break;
            case ActionOperation::split:
                impl_->client->split_async().get();
                break;
            case ActionOperation::skip:
                impl_->client->skip_async().get();
                break;
            case ActionOperation::undo:
                impl_->client->undo_async().get();
                break;
            case ActionOperation::reset:
                impl_->client->reset_async().get();
                break;
            case ActionOperation::pause:
                impl_->client->pause_async().get();
                break;
            case ActionOperation::resume:
                impl_->client->resume_async().get();
                break;
        }
        return BridgeControlResult{BridgeControlStatus::ok, {}};
    } catch (const livesplit::bridge::error& error) {
        const auto kind = map_error_kind(error.kind());
        if (kind == BridgeErrorKind::control_result_unknown) {
            return BridgeControlResult{
                BridgeControlStatus::unknown,
                std::string{"control result unknown: "} + error.what()
            };
        }
        if (kind == BridgeErrorKind::connection_lost || kind == BridgeErrorKind::closed) {
            return BridgeControlResult{
                BridgeControlStatus::connection_lost,
                std::string{"connection lost: "} + error.what()
            };
        }
        return BridgeControlResult{
            BridgeControlStatus::error,
            std::string{"control failed: "} + error.what()
        };
    }
}

void LiveSplitBridgeClient::close() noexcept {
    if (impl_ && impl_->client) {
        impl_->client->close();
    }
}

}  // namespace divergencesplitter
