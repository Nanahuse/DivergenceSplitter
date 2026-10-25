#include "divergencesplitter/livesplit/adapter.hpp"

#include <algorithm>
#include <utility>

namespace divergencesplitter {

LiveSplitBridgeAdapter::LiveSplitBridgeAdapter(BridgeClient& client) : client_(client) {}

LiveSplitUpdate LiveSplitBridgeAdapter::attach() {
    auto snapshot = client_.synchronize();
    reset_revisions();
    return make_update(UpdateKind::initial, snapshot);
}

LiveSplitUpdate LiveSplitBridgeAdapter::synchronize(BridgeEventKind event) {
    auto snapshot = client_.synchronize();
    const UpdateKind kind =
        event == BridgeEventKind::context_changed || event == BridgeEventKind::other
        ? UpdateKind::periodic
        : UpdateKind::transition;
    return make_update(kind, snapshot);
}

LiveSplitUpdate LiveSplitBridgeAdapter::synchronize_after_control() {
    auto snapshot = client_.synchronize();
    return make_update(UpdateKind::transition, snapshot);
}

void LiveSplitBridgeAdapter::reset_revisions() {
    state_revision_ = 0;
    run_revision_ = 0;
    session_id_ = 0;
    last_.reset();
    last_segments_.clear();
    initialized_ = false;
}

LiveSplitUpdate LiveSplitBridgeAdapter::make_update(
    UpdateKind kind,
    const BridgeSnapshot& snapshot
) {
    const bool session_changed = initialized_ && snapshot.session_id != session_id_;
    if (!initialized_ || session_changed) {
        reset_revisions();
    }

    const bool run_changed =
        !last_.has_value() ||
        last_segments_ != snapshot.segment_names ||
        session_changed;

    if (kind == UpdateKind::initial || kind == UpdateKind::resync ||
        kind == UpdateKind::transition) {
        ++state_revision_;
    } else if (run_changed || !last_.has_value() ||
               last_->phase != snapshot.phase ||
               last_->split_index != snapshot.split_index ||
               last_->split_count != snapshot.split_count) {
        ++state_revision_;
    }
    if (run_changed) {
        ++run_revision_;
    }
    if (state_revision_ == 0) {
        state_revision_ = 1;
    }
    if (run_revision_ == 0) {
        run_revision_ = 1;
    }

    session_id_ = snapshot.session_id;
    last_ = snapshot;
    last_segments_ = snapshot.segment_names;
    initialized_ = true;

    LiveSplitUpdate update;
    update.kind = session_changed ? UpdateKind::resync : kind;
    update.snapshot = LiveSplitSnapshot{
        snapshot.session_id,
        state_revision_,
        run_revision_,
        snapshot.phase,
        snapshot.split_index,
        snapshot.split_count,
    };

    RunInfo run_info;
    run_info.session_id = snapshot.session_id;
    run_info.run_revision = run_revision_;
    run_info.segments.reserve(snapshot.segment_names.size());
    for (std::size_t index = 0; index < snapshot.segment_names.size(); ++index) {
        run_info.segments.push_back(
            SegmentInfo{static_cast<int>(index), snapshot.segment_names[index]}
        );
    }
    update.run_info = std::move(run_info);
    return update;
}

}  // namespace divergencesplitter
