#pragma once

#include <opencv2/core.hpp>

#include <optional>
#include <string>
#include <vector>

#include "divergencesplitter/detector/detector.hpp"

namespace divergencesplitter {

class TemplateMatchDetector final : public Detector {
public:
    explicit TemplateMatchDetector(cv::Mat reference, std::optional<Region> roi = std::nullopt);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "template_match"; }
    [[nodiscard]] std::string cache_key() const override { return key_; }
    [[nodiscard]] DetectionResult detect(FrameContext& context) const override;
    [[nodiscard]] std::vector<ReferenceImage> reference_images() const override;
    [[nodiscard]] std::string describe() const override;

    [[nodiscard]] const std::optional<Region>& roi() const noexcept { return roi_; }

private:
    cv::Mat reference_;
    cv::Mat template_;
    cv::Mat mask_;
    std::optional<Region> roi_;
    std::string key_;
};

class MeanAbsoluteSimilarityDetector final : public Detector {
public:
    explicit MeanAbsoluteSimilarityDetector(cv::Mat reference, std::optional<Region> roi = std::nullopt);

    [[nodiscard]] std::string_view type_name() const noexcept override {
        return "mean_absolute_similarity";
    }
    [[nodiscard]] std::string cache_key() const override { return key_; }
    [[nodiscard]] DetectionResult detect(FrameContext& context) const override;
    [[nodiscard]] std::vector<ReferenceImage> reference_images() const override;
    [[nodiscard]] std::string describe() const override;

private:
    cv::Mat reference_;
    cv::Mat prepared_;
    cv::Mat mask_;
    std::size_t component_count_{};
    std::optional<Region> roi_;
    std::string key_;
};

class RootMeanSquareSimilarityDetector final : public Detector {
public:
    explicit RootMeanSquareSimilarityDetector(cv::Mat reference, std::optional<Region> roi = std::nullopt);

    [[nodiscard]] std::string_view type_name() const noexcept override {
        return "root_mean_square_similarity";
    }
    [[nodiscard]] std::string cache_key() const override { return key_; }
    [[nodiscard]] DetectionResult detect(FrameContext& context) const override;
    [[nodiscard]] std::vector<ReferenceImage> reference_images() const override;
    [[nodiscard]] std::string describe() const override;

private:
    cv::Mat reference_;
    cv::Mat prepared_;
    cv::Mat mask_;
    std::size_t component_count_{};
    std::optional<Region> roi_;
    std::string key_;
};

class DifferenceHashSimilarityDetector final : public Detector {
public:
    explicit DifferenceHashSimilarityDetector(
        cv::Mat reference,
        int hash_size = 8,
        std::optional<Region> roi = std::nullopt
    );

    [[nodiscard]] std::string_view type_name() const noexcept override {
        return "difference_hash_similarity";
    }
    [[nodiscard]] std::string cache_key() const override { return key_; }
    [[nodiscard]] DetectionResult detect(FrameContext& context) const override;
    [[nodiscard]] std::vector<ReferenceImage> reference_images() const override;
    [[nodiscard]] std::string describe() const override;

private:
    cv::Mat reference_;
    cv::Mat reference_hash_;
    int hash_size_{8};
    std::optional<Region> roi_;
    std::string key_;
};

class MeanBrightnessDetector final : public Detector {
public:
    explicit MeanBrightnessDetector(std::optional<Region> roi = std::nullopt);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "mean_brightness"; }
    [[nodiscard]] std::string cache_key() const override { return key_; }
    [[nodiscard]] DetectionResult detect(FrameContext& context) const override;
    [[nodiscard]] std::string describe() const override;

private:
    std::optional<Region> roi_;
    std::string key_;
};

class ColorRangeDetector final : public Detector {
public:
    ColorRangeDetector(
        std::vector<double> lower,
        std::vector<double> upper,
        std::optional<Region> roi = std::nullopt
    );

    [[nodiscard]] std::string_view type_name() const noexcept override { return "color_range"; }
    [[nodiscard]] std::string cache_key() const override { return key_; }
    [[nodiscard]] DetectionResult detect(FrameContext& context) const override;
    [[nodiscard]] std::string describe() const override;

private:
    std::vector<double> lower_;
    std::vector<double> upper_;
    std::optional<Region> roi_;
    std::string key_;
};

class PhaseCorrelationDetector final : public Detector {
public:
    explicit PhaseCorrelationDetector(cv::Mat reference, std::optional<Region> roi = std::nullopt);

    [[nodiscard]] std::string_view type_name() const noexcept override { return "phase_correlation"; }
    [[nodiscard]] std::string cache_key() const override { return key_; }
    [[nodiscard]] DetectionResult detect(FrameContext& context) const override;
    [[nodiscard]] std::vector<ReferenceImage> reference_images() const override;
    [[nodiscard]] std::string describe() const override;

private:
    cv::Mat reference_;
    cv::Mat reference_gray_;
    std::optional<Region> roi_;
    std::string key_;
};

}  // namespace divergencesplitter
