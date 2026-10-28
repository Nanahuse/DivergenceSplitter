#pragma once

#include <opencv2/core.hpp>

#include <chrono>
#include <memory>
#include <stdexcept>
#include <string>

#include "divergencesplitter/clock.hpp"

namespace divergencesplitter {

class FrameSourceError : public std::runtime_error {
public:
    FrameSourceError(std::string message, bool retryable)
        : std::runtime_error(std::move(message)), retryable_(retryable) {}

    [[nodiscard]] bool retryable() const noexcept { return retryable_; }

private:
    bool retryable_;
};

class FrameSource {
public:
    virtual ~FrameSource() = default;

    virtual void open() = 0;
    [[nodiscard]] virtual cv::Mat read(MonotonicTime& captured_at) = 0;
    virtual void close() noexcept = 0;
    [[nodiscard]] virtual std::string describe() const = 0;
};

struct CameraSourceOptions {
    int device_index{};
    int backend{};
    int width{};
    int height{};
    double fps{};
    std::string subtype_guid;
    bool enforce_mode{false};
    bool request_60_fps{false};
};

class CameraFrameSource final : public FrameSource {
public:
    explicit CameraFrameSource(CameraSourceOptions options);
    ~CameraFrameSource() override;

    void open() override;
    [[nodiscard]] cv::Mat read(MonotonicTime& captured_at) override;
    void close() noexcept override;
    [[nodiscard]] std::string describe() const override;

private:
    CameraSourceOptions options_;
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

struct VideoFileSourceOptions {
    std::string path;
};

class VideoFileFrameSource final : public FrameSource {
public:
    explicit VideoFileFrameSource(VideoFileSourceOptions options);
    ~VideoFileFrameSource() override;

    void open() override;
    [[nodiscard]] cv::Mat read(MonotonicTime& captured_at) override;
    void close() noexcept override;
    [[nodiscard]] std::string describe() const override;

private:
    VideoFileSourceOptions options_;
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

struct NdiSourceOptions {
    std::string name;
};

class NdiFrameSource final : public FrameSource {
public:
    explicit NdiFrameSource(NdiSourceOptions options);
    ~NdiFrameSource() override;

    void open() override;
    [[nodiscard]] cv::Mat read(MonotonicTime& captured_at) override;
    void close() noexcept override;
    [[nodiscard]] std::string describe() const override;

private:
    NdiSourceOptions options_;
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace divergencesplitter
