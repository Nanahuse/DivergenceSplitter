#pragma once

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

#include "divergencesplitter/livesplit/bridge_client.hpp"
#include "divergencesplitter/runtime/models.hpp"

namespace divergencesplitter {

class LiveSplitBridgeAdapter {
public:
    explicit LiveSplitBridgeAdapter(BridgeClient& client);

    [[nodiscard]] LiveSplitUpdate attach();
    [[nodiscard]] std::optional<LiveSplitUpdate> apply_event(const BridgeEvent& event);
    [[nodiscard]] LiveSplitUpdate synchronize(BridgeEventKind event);

    [[nodiscard]] BridgeClient& client() noexcept { return client_; }

private:
    [[nodiscard]] LiveSplitUpdate make_update(UpdateKind kind, const BridgeSnapshot& snapshot);
    void reset_revisions();

    BridgeClient& client_;
    std::uint32_t session_id_{};
    std::uint64_t state_revision_{};
    std::uint64_t run_revision_{};
    bool initialized_{false};
    std::optional<BridgeSnapshot> last_;
    std::vector<std::string> last_segments_;
};

}  // namespace divergencesplitter
