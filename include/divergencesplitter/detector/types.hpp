#pragma once

#include <opencv2/core.hpp>

#include <optional>
#include <string>

namespace divergencesplitter {

struct Region {
    int x{};
    int y{};
    int width{};
    int height{};

    [[nodiscard]] bool valid() const noexcept {
        return x >= 0 && y >= 0 && width > 0 && height > 0;
    }

    friend bool operator==(const Region&, const Region&) = default;
};

struct DetectionResult {
    double score{};
};

struct ReferenceImage {
    std::string label;
    cv::Mat image;
};

[[nodiscard]] inline std::optional<cv::Rect> to_rect(const std::optional<Region>& region) {
    if (!region.has_value()) {
        return std::nullopt;
    }
    return cv::Rect{region->x, region->y, region->width, region->height};
}

}  // namespace divergencesplitter
