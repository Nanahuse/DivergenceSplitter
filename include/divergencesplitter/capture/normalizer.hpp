#pragma once

#include <opencv2/core.hpp>

#include <optional>
#include <stdexcept>
#include <string>

namespace divergencesplitter {

enum class ResizeInterpolation {
    area,
    nearest,
    linear,
    cubic,
    lanczos4,
};

[[nodiscard]] std::string_view to_string(ResizeInterpolation interpolation) noexcept;
[[nodiscard]] std::optional<ResizeInterpolation> parse_resize_interpolation(std::string_view value) noexcept;

struct CropMargins {
    int left{};
    int right{};
    int top{};
    int bottom{};

    friend bool operator==(const CropMargins&, const CropMargins&) = default;
};

struct OutputSize {
    int width{};
    int height{};

    friend bool operator==(const OutputSize&, const OutputSize&) = default;
};

class FrameNormalizationError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class FrameNormalizer {
public:
    FrameNormalizer(
        std::optional<CropMargins> crop_margins = std::nullopt,
        std::optional<OutputSize> output_size = std::nullopt,
        ResizeInterpolation interpolation = ResizeInterpolation::area
    );

    [[nodiscard]] cv::Mat normalize(const cv::Mat& image) const;

    [[nodiscard]] const std::optional<CropMargins>& crop_margins() const noexcept {
        return crop_margins_;
    }
    [[nodiscard]] const std::optional<OutputSize>& output_size() const noexcept {
        return output_size_;
    }
    [[nodiscard]] ResizeInterpolation interpolation() const noexcept { return interpolation_; }

private:
    std::optional<CropMargins> crop_margins_;
    std::optional<OutputSize> output_size_;
    ResizeInterpolation interpolation_{ResizeInterpolation::area};
};

}  // namespace divergencesplitter
