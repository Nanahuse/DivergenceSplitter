#include "ndi_discovery.hpp"

#include <stdexcept>
#include <utility>

namespace divergencesplitter::ui {

NdiDiscoveryWorker::NdiDiscoveryWorker(Discovery discovery)
    : discovery_(std::move(discovery)) {}

NdiDiscoveryWorker::~NdiDiscoveryWorker() {
    stop();
}

void NdiDiscoveryWorker::start() {
    if (busy_.exchange(true, std::memory_order_acq_rel)) {
        return;
    }
    if (thread_.joinable()) {
        thread_.join();
    }
    result_ready_.store(false, std::memory_order_release);
    {
        std::scoped_lock lock{mutex_};
        result_.reset();
    }
    thread_ = std::thread([this] { run(); });
}

void NdiDiscoveryWorker::stop() {
    if (thread_.joinable()) {
        thread_.join();
    }
    busy_.store(false, std::memory_order_release);
    result_ready_.store(false, std::memory_order_release);
    std::scoped_lock lock{mutex_};
    result_.reset();
}

std::optional<NdiDiscoveryResult> NdiDiscoveryWorker::take_result() {
    if (!result_ready_.exchange(false, std::memory_order_acq_rel)) {
        return std::nullopt;
    }
    if (thread_.joinable()) {
        thread_.join();
    }
    std::scoped_lock lock{mutex_};
    auto result = std::move(result_);
    result_.reset();
    return result;
}

void NdiDiscoveryWorker::run() {
    NdiDiscoveryResult result;
    try {
        if (!discovery_) {
            throw std::runtime_error("NDI discovery is unavailable");
        }
        result.sources = discovery_();
    } catch (const std::exception& error) {
        result.error = error.what();
    }
    {
        std::scoped_lock lock{mutex_};
        result_ = std::move(result);
    }
    result_ready_.store(true, std::memory_order_release);
    busy_.store(false, std::memory_order_release);
}

}  // namespace divergencesplitter::ui
