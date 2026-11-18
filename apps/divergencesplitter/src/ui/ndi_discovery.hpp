#pragma once

#include <atomic>
#include <functional>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace divergencesplitter::ui {

struct NdiDiscoveryResult {
    std::vector<std::string> sources;
    std::string error;
};

// Runs NDI discovery off the GUI thread and publishes exactly one result.
// Completion flags are atomic; the result payload is mutex-protected.
class NdiDiscoveryWorker {
public:
    using Discovery = std::function<std::vector<std::string>()>;

    explicit NdiDiscoveryWorker(Discovery discovery = {});
    ~NdiDiscoveryWorker();

    NdiDiscoveryWorker(const NdiDiscoveryWorker&) = delete;
    NdiDiscoveryWorker& operator=(const NdiDiscoveryWorker&) = delete;

    void start();
    void stop();
    [[nodiscard]] bool busy() const noexcept {
        return busy_.load(std::memory_order_acquire);
    }
    [[nodiscard]] std::optional<NdiDiscoveryResult> take_result();

private:
    void run();

    Discovery discovery_;
    mutable std::mutex mutex_;
    std::thread thread_;
    std::atomic_bool busy_{false};
    std::atomic_bool result_ready_{false};
    std::optional<NdiDiscoveryResult> result_;
};

}  // namespace divergencesplitter::ui
