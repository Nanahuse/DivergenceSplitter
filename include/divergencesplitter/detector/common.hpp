#pragma once

#include <opencv2/core.hpp>

#include <optional>
#include <string>

#include "divergencesplitter/detector/types.hpp"
#include "divergencesplitter/frame.hpp"

namespace divergencesplitter::detail {

struct PreparedReference {
    cv::Mat image;
    cv::Mat mask;
};

[[nodiscard]] PreparedReference prepare_reference_alpha(const cv::Mat& reference);
[[nodiscard]] cv::Mat to_gray(const cv::Mat& image);
[[nodiscard]] cv::Mat dhash_bits(const cv::Mat& gray, int hash_size);
[[nodiscard]] double clamp_unit(double value);
[[nodiscard]] cv::Mat frame_region(const cv::Mat& image, const std::optional<Region>& region);
[[nodiscard]] cv::Mat frame_gray(
    FrameContext& context,
    const std::optional<Region>& region
);
[[nodiscard]] std::string region_key(const std::optional<Region>& region);
[[nodiscard]] std::string mat_hash(const cv::Mat& image);
[[nodiscard]] std::string make_detector_key(
    std::string_view type,
    const std::optional<Region>& region,
    std::string_view extra,
    const cv::Mat& reference = {}
);

}  // namespace divergencesplitter::detail
