#pragma once

#include <opencv2/core.hpp>

#include <functional>
#include <future>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>

#include "divergencesplitter/clock.hpp"
#include "divergencesplitter/detector/types.hpp"

namespace divergencesplitter {

struct Frame {
    cv::Mat image;
    MonotonicTime captured_at;
};

class FrameCache {
public:
    FrameCache() = default;
    FrameCache(const FrameCache&) = delete;
    FrameCache& operator=(const FrameCache&) = delete;
    FrameCache(FrameCache&& other) noexcept {
        std::scoped_lock lock{other.mutex_};
        images_ = std::move(other.images_);
        detections_ = std::move(other.detections_);
    }
    FrameCache& operator=(FrameCache&& other) noexcept {
        if (this == &other) {
            return *this;
        }
        std::scoped_lock lock{mutex_, other.mutex_};
        images_ = std::move(other.images_);
        detections_ = std::move(other.detections_);
        return *this;
    }

    [[nodiscard]] cv::Mat gray(
        const std::string& key,
        const std::function<cv::Mat()>& compute
    ) const {
        return get(images_, key, compute);
    }

    [[nodiscard]] DetectionResult detection(
        const std::string& key,
        const std::function<DetectionResult()>& compute
    ) const {
        return get(detections_, key, compute);
    }

    [[nodiscard]] std::optional<cv::Mat> cached_gray(const std::string& key) const {
        return peek(images_, key);
    }

    [[nodiscard]] std::optional<DetectionResult> cached_detection(const std::string& key) const {
        return peek(detections_, key);
    }

    [[nodiscard]] bool has_detection(const std::string& key) const {
        return cached_detection(key).has_value();
    }

    void seed_gray(const std::string& key, const cv::Mat& image) const {
        if (image.empty()) {
            return;
        }
        std::scoped_lock lock{mutex_};
        if (!images_.contains(key)) {
            std::promise<cv::Mat> promise;
            auto future = promise.get_future().share();
            promise.set_value(image);
            images_.emplace(key, std::move(future));
        }
    }

private:
    template <typename T>
    [[nodiscard]] std::optional<T> peek(
        std::unordered_map<std::string, std::shared_future<T>>& values,
        const std::string& key
    ) const {
        std::scoped_lock lock{mutex_};
        auto it = values.find(key);
        if (it == values.end()) {
            return std::nullopt;
        }
        if (it->second.wait_for(std::chrono::seconds{0}) != std::future_status::ready) {
            return std::nullopt;
        }
        return it->second.get();
    }

    template <typename T>
    [[nodiscard]] T get(
        std::unordered_map<std::string, std::shared_future<T>>& values,
        const std::string& key,
        const std::function<T()>& compute
    ) const {
        std::shared_future<T> future;
        std::shared_ptr<std::promise<T>> promise;
        {
            std::scoped_lock lock{mutex_};
            auto it = values.find(key);
            if (it != values.end()) {
                future = it->second;
            } else {
                promise = std::make_shared<std::promise<T>>();
                future = promise->get_future().share();
                values.emplace(key, future);
            }
        }
        if (!promise) {
            return future.get();
        }

        try {
            T value = compute();
            promise->set_value(value);
            return value;
        } catch (...) {
            {
                std::scoped_lock lock{mutex_};
                values.erase(key);
            }
            promise->set_exception(std::current_exception());
            throw;
        }
    }

    mutable std::mutex mutex_;
    mutable std::unordered_map<std::string, std::shared_future<cv::Mat>> images_;
    mutable std::unordered_map<std::string, std::shared_future<DetectionResult>> detections_;
};

struct SharedFrameEvaluation {
    Frame frame;
    MonotonicTime now;
    mutable FrameCache cache;
};

class FrameContext {
public:
    explicit FrameContext(std::shared_ptr<SharedFrameEvaluation> shared)
        : shared_(std::move(shared)) {}

    FrameContext(Frame frame, MonotonicTime now)
        : shared_(std::make_shared<SharedFrameEvaluation>(
              SharedFrameEvaluation{std::move(frame), now, {}})) {}

    [[nodiscard]] const Frame& frame() const { return shared_->frame; }
    [[nodiscard]] MonotonicTime now() const { return shared_->now; }
    [[nodiscard]] FrameCache& cache() const { return shared_->cache; }
    [[nodiscard]] const std::shared_ptr<SharedFrameEvaluation>& shared() const { return shared_; }

private:
    std::shared_ptr<SharedFrameEvaluation> shared_;
};

}  // namespace divergencesplitter
