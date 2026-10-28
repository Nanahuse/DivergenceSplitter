#include "divergencesplitter/capture/normalizer.hpp"

#include <opencv2/imgproc.hpp>

#include <stdexcept>

namespace divergencesplitter {
namespace {

int cv_interpolation(ResizeInterpolation interpolation) {
    switch (interpolation) {
        case ResizeInterpolation::area:
            return cv::INTER_AREA;
        case ResizeInterpolation::nearest:
            return cv::INTER_NEAREST;
        case ResizeInterpolation::linear:
            return cv::INTER_LINEAR;
        case ResizeInterpolation::cubic:
            return cv::INTER_CUBIC;
        case ResizeInterpolation::lanczos4:
            return cv::INTER_LANCZOS4;
    }
    return cv::INTER_AREA;
}

}  // namespace

std::string_view to_string(ResizeInterpolation interpolation) noexcept {
    switch (interpolation) {
        case ResizeInterpolation::area:
            return "area";
        case ResizeInterpolation::nearest:
            return "nearest";
        case ResizeInterpolation::linear:
            return "linear";
        case ResizeInterpolation::cubic:
            return "cubic";
        case ResizeInterpolation::lanczos4:
            return "lanczos4";
    }
    return "area";
}

std::optional<ResizeInterpolation> parse_resize_interpolation(std::string_view value) noexcept {
    if (value == "area") {
        return ResizeInterpolation::area;
    }
    if (value == "nearest") {
        return ResizeInterpolation::nearest;
    }
    if (value == "linear") {
        return ResizeInterpolation::linear;
    }
    if (value == "cubic") {
        return ResizeInterpolation::cubic;
    }
    if (value == "lanczos4") {
        return ResizeInterpolation::lanczos4;
    }
    return std::nullopt;
}

FrameNormalizer::FrameNormalizer(
    std::optional<CropMargins> crop_margins,
    std::optional<OutputSize> output_size,
    ResizeInterpolation interpolation
)
    : crop_margins_(crop_margins),
      output_size_(output_size),
      interpolation_(interpolation) {
    if (crop_margins_.has_value()) {
        const auto& margins = *crop_margins_;
        if (margins.left < 0 || margins.right < 0 || margins.top < 0 ||
            margins.bottom < 0) {
            throw std::invalid_argument("crop margins must be non-negative");
        }
    }
    if (output_size_.has_value()) {
        const auto& size = *output_size_;
        if (size.width <= 0 || size.height <= 0) {
            throw std::invalid_argument("output size must be positive");
        }
    }
}

cv::Mat FrameNormalizer::normalize(const cv::Mat& image) const {
    if (image.empty()) {
        throw FrameNormalizationError("frame is empty");
    }
    cv::Mat cropped;
    const cv::Mat* current = &image;
    if (crop_margins_.has_value()) {
        const auto& margins = *crop_margins_;
        if (margins.left + margins.right >= image.cols ||
            margins.top + margins.bottom >= image.rows) {
            throw FrameNormalizationError("crop margins do not fit in image");
        }
        const int width = image.cols - margins.left - margins.right;
        const int height = image.rows - margins.top - margins.bottom;
        cropped = image(cv::Rect{margins.left, margins.top, width, height}).clone();
        current = &cropped;
    }
    if (output_size_.has_value()) {
        cv::Mat resized;
        cv::resize(
            *current,
            resized,
            cv::Size{output_size_->width, output_size_->height},
            0.0,
            0.0,
            cv_interpolation(interpolation_)
        );
        return resized;
    }
    return *current;
}

}  // namespace divergencesplitter
