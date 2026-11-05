#include "divergencesplitter/detector/detectors.hpp"

#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>

#include "divergencesplitter/detector/common.hpp"

namespace divergencesplitter {
namespace {

constexpr std::uint64_t kFnvOffset = 1469598103934665603ULL;
constexpr std::uint64_t kFnvPrime = 1099511628211ULL;

std::uint64_t fnv1a(std::uint64_t hash, const void* data, std::size_t size) {
    const auto* bytes = static_cast<const unsigned char*>(data);
    for (std::size_t index = 0; index < size; ++index) {
        hash ^= bytes[index];
        hash *= kFnvPrime;
    }
    return hash;
}

std::string sanitize_double(double value) {
    std::ostringstream stream;
    stream.precision(17);
    stream << value;
    return stream.str();
}

void require_finite(const cv::Mat& image, std::string_view context) {
    if (image.empty()) {
        throw std::invalid_argument(std::string(context) + ": image is empty");
    }
    if (image.depth() == CV_32F || image.depth() == CV_64F) {
        if (!cv::checkRange(image, true)) {
            throw std::invalid_argument(std::string(context) + ": image values must be finite");
        }
    }
}

int channel_count(const cv::Mat& image) {
    if (image.dims != 2) {
        throw std::invalid_argument("unsupported image dimensions");
    }
    return image.channels();
}

void validate_region(const cv::Mat& image, const std::optional<Region>& region) {
    if (!region.has_value()) {
        return;
    }
    if (!region->valid()) {
        throw std::invalid_argument("region must be non-negative with positive dimensions");
    }
    if (region->x + region->width > image.cols || region->y + region->height > image.rows) {
        throw std::invalid_argument("region does not fit in image");
    }
}

std::string roi_suffix(const std::optional<Region>& region) {
    if (!region.has_value()) {
        return "full";
    }
    std::ostringstream stream;
    stream << region->x << ',' << region->y << ',' << region->width << ',' << region->height;
    return stream.str();
}

cv::Mat to_float64(const cv::Mat& image) {
    cv::Mat result;
    image.convertTo(result, CV_64F);
    return result;
}

double masked_sum(const cv::Mat& image, const cv::Mat& mask, bool squared) {
    cv::Mat values;
    if (squared) {
        cv::multiply(image, image, values);
    } else {
        cv::absdiff(image, cv::Mat::zeros(image.size(), image.type()), values);
    }
    if (!mask.empty()) {
        cv::Mat mask_float;
        mask.convertTo(mask_float, CV_64F, 1.0 / 255.0);
        if (values.channels() > 1) {
            std::vector<cv::Mat> channels;
            cv::split(values, channels);
            cv::Mat total = cv::Mat::zeros(values.size(), CV_64F);
            for (auto& channel : channels) {
                cv::Mat weighted;
                cv::multiply(channel, mask_float, weighted);
                total += weighted;
            }
            values = total;
        } else {
            cv::multiply(values, mask_float, values);
        }
    }
    double total = 0.0;
    for (int channel = 0; channel < values.channels(); ++channel) {
        total += cv::sum(values)[channel];
    }
    return total;
}

void require_bgr8(const cv::Mat& image) {
    if (image.empty() || image.dims != 2 || image.type() != CV_8UC3) {
        throw std::invalid_argument("image must be a non-empty 8-bit 3-channel BGR image");
    }
}

void validate_masked_frame(const cv::Mat& image, const cv::Mat& mask) {
    require_bgr8(image);
    if (!mask.empty() && image.size() != mask.size()) {
        throw std::invalid_argument("frame shape must match reference shape when masked");
    }
}

cv::Mat color_histogram(const cv::Mat& image, const cv::Mat& mask) {
    const int channels[] = {2, 1, 0};
    const int bins[] = {8, 8, 8};
    const float range[] = {0.0F, 256.0F};
    const float* ranges[] = {range, range, range};
    cv::Mat histogram;
    cv::calcHist(&image, 1, channels, mask, histogram, 3, bins, ranges);
    cv::normalize(histogram, histogram);
    return histogram;
}

cv::Mat perceptual_hash(const cv::Mat& image, const cv::Mat& mask) {
    cv::Mat source;
    if (!mask.empty()) {
        cv::bitwise_and(image, image, source, mask);
    } else {
        source = image;
    }
    cv::Mat resized;
    // The Python detector downsamples before calling OpenCV's PHash.
    cv::resize(source, resized, cv::Size{8, 8}, 0.0, 0.0, cv::INTER_AREA);
    // Match opencv_contrib 4.12.0/modules/img_hash/src/phash.cpp, including
    // uint8 grayscale rounding, a float mean, and least-significant-bit order.
    cv::Mat expanded;
    cv::resize(resized, expanded, cv::Size{32, 32}, 0.0, 0.0, cv::INTER_LINEAR_EXACT);
    cv::Mat gray;
    cv::cvtColor(expanded, gray, cv::COLOR_BGR2GRAY);
    gray.convertTo(gray, CV_32F);
    cv::Mat coefficients;
    cv::dct(gray, coefficients);
    cv::Mat low = coefficients(cv::Rect{0, 0, 8, 8}).clone();
    low.at<float>(0, 0) = 0.0F;
    const float mean = static_cast<float>(cv::mean(low)[0]);
    cv::Mat bits;
    cv::compare(low, mean, bits, cv::CMP_GT);
    cv::Mat hash = cv::Mat::zeros(1, 8, CV_8U);
    for (int row = 0; row < 8; ++row) {
        for (int column = 0; column < 8; ++column) {
            if (bits.at<std::uint8_t>(row, column) != 0) {
                hash.at<std::uint8_t>(0, row) |= static_cast<std::uint8_t>(1U << column);
            }
        }
    }
    return hash;
}

cv::Mat frame_dhash_cached(
    FrameContext& context,
    int hash_size,
    const std::optional<Region>& region
) {
    const std::string key =
        "frame-dhash:" + std::to_string(hash_size) + ':' + detail::region_key(region);
    return context.cache().gray(key, [&context, hash_size, &region]() {
        return detail::dhash_bits(detail::frame_gray(context, region), hash_size);
    });
}

}  // namespace

namespace detail {

PreparedReference prepare_reference_alpha(const cv::Mat& reference) {
    if (reference.empty()) {
        throw std::invalid_argument("reference image is empty");
    }
    if (reference.dims != 2) {
        throw std::invalid_argument("reference image must be two-dimensional");
    }

    const int channels = reference.channels();
    if (channels == 4) {
        std::vector<cv::Mat> parts;
        cv::split(reference, parts);
        const cv::Mat& alpha = parts[3];
        double minimum = 0.0;
        double maximum = 0.0;
        cv::minMaxLoc(alpha, &minimum, &maximum);
        if (maximum <= 0.0) {
            throw std::invalid_argument("reference alpha mask has no valid pixels");
        }
        cv::Mat binary;
        cv::compare(alpha, 255, binary, cv::CMP_EQ);
        if (cv::countNonZero(binary) != cv::countNonZero(alpha)) {
            throw std::invalid_argument("reference alpha must contain only 0 or 255");
        }
        if (cv::countNonZero(binary) == alpha.total()) {
            cv::Mat bgr;
            cv::cvtColor(reference, bgr, cv::COLOR_BGRA2BGR);
            return PreparedReference{bgr, {}};
        }
        cv::Mat bgr;
        cv::cvtColor(reference, bgr, cv::COLOR_BGRA2BGR);
        return PreparedReference{bgr, binary};
    }
    if (channels != 1 && channels != 3) {
        throw std::invalid_argument("unsupported reference channel layout");
    }
    return PreparedReference{reference, {}};
}

cv::Mat to_gray(const cv::Mat& image) {
    require_finite(image, "grayscale conversion");
    cv::Mat float_image;
    image.convertTo(float_image, CV_32F);
    cv::Mat gray;
    switch (float_image.channels()) {
        case 1:
            gray = float_image;
            break;
        case 3:
            cv::cvtColor(float_image, gray, cv::COLOR_BGR2GRAY);
            break;
        case 4:
            cv::cvtColor(float_image, gray, cv::COLOR_BGRA2GRAY);
            break;
        default:
            throw std::invalid_argument("unsupported image shape for grayscale");
    }
    return gray;
}

cv::Mat dhash_bits(const cv::Mat& gray, int hash_size) {
    if (hash_size <= 0) {
        throw std::invalid_argument("hash_size must be positive");
    }
    cv::Mat resized;
    cv::resize(
        gray,
        resized,
        cv::Size{hash_size + 1, hash_size},
        0.0,
        0.0,
        cv::INTER_AREA
    );
    cv::Mat bits(resized.rows, resized.cols - 1, CV_8U);
    for (int row = 0; row < resized.rows; ++row) {
        const float* source = resized.ptr<float>(row);
        auto* target = bits.ptr<std::uint8_t>(row);
        for (int column = 0; column < bits.cols; ++column) {
            target[column] = source[column + 1] > source[column] ? 1 : 0;
        }
    }
    return bits;
}

double clamp_unit(double value) {
    return std::clamp(value, 0.0, 1.0);
}

cv::Mat frame_region(const cv::Mat& image, const std::optional<Region>& region) {
    if (image.empty()) {
        throw std::invalid_argument("frame is empty");
    }
    validate_region(image, region);
    if (!region.has_value()) {
        return image;
    }
    return image(cv::Rect{region->x, region->y, region->width, region->height});
}

cv::Mat frame_gray(FrameContext& context, const std::optional<Region>& region) {
    const std::string key = "frame-gray:" + region_key(region);
    return context.cache().gray(key, [&context, &region]() {
        return to_gray(frame_region(context.frame().image, region));
    });
}

std::string region_key(const std::optional<Region>& region) {
    return roi_suffix(region);
}

std::string mat_hash(const cv::Mat& image) {
    if (image.empty()) {
        return "empty";
    }
    std::uint64_t hash = kFnvOffset;
    hash = fnv1a(hash, &image.rows, sizeof(image.rows));
    hash = fnv1a(hash, &image.cols, sizeof(image.cols));
    const int type = image.type();
    hash = fnv1a(hash, &type, sizeof(type));
    for (int row = 0; row < image.rows; ++row) {
        hash = fnv1a(
            hash,
            image.ptr(row),
            static_cast<std::size_t>(image.cols) * image.elemSize()
        );
    }
    std::ostringstream stream;
    stream << std::hex << hash;
    return stream.str();
}

std::string make_detector_key(
    std::string_view type,
    const std::optional<Region>& region,
    std::string_view extra,
    const cv::Mat& reference
) {
    std::string key{type};
    key += ':';
    key += region_key(region);
    key += ':';
    key += extra;
    if (!reference.empty()) {
        key += ':';
        key += mat_hash(reference);
    }
    return key;
}

}  // namespace detail

DetectionResult detect_cached(FrameContext& context, const DetectorPtr& detector) {
    if (!detector) {
        throw std::invalid_argument("detector is null");
    }
    return context.cache().detection(detector->cache_key(), [&context, &detector]() {
        return detector->detect(context);
    });
}

TemplateMatchDetector::TemplateMatchDetector(cv::Mat reference, std::optional<Region> roi)
    : reference_(reference.clone()), roi_(roi) {
    auto prepared = detail::prepare_reference_alpha(reference_);
    double minimum = 0.0;
    double maximum = 0.0;
    bool byte_image = true;
    for (int channel = 0; channel < prepared.image.channels(); ++channel) {
        cv::Mat plane;
        cv::extractChannel(prepared.image, plane, channel);
        cv::minMaxLoc(plane, &minimum, &maximum);
        if ((prepared.image.depth() != CV_8U && prepared.image.depth() != CV_16U) ||
            minimum < 0.0 || maximum > 255.0) {
            byte_image = false;
        }
    }
    if (byte_image) {
        prepared.image.convertTo(template_, CV_8U);
    } else {
        prepared.image.convertTo(template_, CV_32F);
    }

    bool any_variation = false;
    for (int channel = 0; channel < template_.channels(); ++channel) {
        cv::Mat plane;
        cv::extractChannel(template_, plane, channel);
        cv::minMaxLoc(plane, &minimum, &maximum);
        if (minimum != maximum) {
            any_variation = true;
            break;
        }
    }
    if (!any_variation) {
        throw std::invalid_argument("template must contain spatial variation");
    }

    mask_ = prepared.mask;
    key_ = detail::make_detector_key("template_match", roi_, "v1", reference_);
}

DetectionResult TemplateMatchDetector::detect(FrameContext& context) const {
    cv::Mat frame = detail::frame_region(context.frame().image, roi_);
    require_finite(frame, "template match");
    if (frame.dims != template_.dims) {
        throw std::invalid_argument("channel layout mismatch");
    }
    if (frame.channels() != template_.channels()) {
        throw std::invalid_argument("channel count mismatch");
    }
    if (template_.rows > frame.rows || template_.cols > frame.cols) {
        throw std::invalid_argument("template is larger than frame");
    }
    if (frame.depth() != template_.depth()) {
        cv::Mat converted;
        frame.convertTo(converted, template_.depth());
        frame = converted;
    }

    cv::Mat response;
    if (!mask_.empty()) {
        cv::matchTemplate(frame, template_, response, cv::TM_CCORR_NORMED, mask_);
    } else {
        cv::matchTemplate(frame, template_, response, cv::TM_CCOEFF_NORMED);
    }
    double minimum = 0.0;
    double score = 0.0;
    cv::minMaxLoc(response, &minimum, &score);
    if (!std::isfinite(score)) {
        throw std::invalid_argument("template match produced a non-finite score");
    }
    if (mask_.empty()) {
        score = (score + 1.0) / 2.0;
    }
    return DetectionResult{detail::clamp_unit(score)};
}

std::vector<ReferenceImage> TemplateMatchDetector::reference_images() const {
    return {ReferenceImage{"reference", reference_.clone()}};
}

std::string TemplateMatchDetector::describe() const {
    return "template match (" + detail::region_key(roi_) + ")";
}

MeanAbsoluteSimilarityDetector::MeanAbsoluteSimilarityDetector(
    cv::Mat reference,
    std::optional<Region> roi
)
    : reference_(reference.clone()), roi_(roi) {
    auto prepared = detail::prepare_reference_alpha(reference_);
    prepared_ = to_float64(prepared.image);
    mask_ = prepared.mask;
    const std::size_t pixels = mask_.empty()
        ? static_cast<std::size_t>(prepared_.rows) * prepared_.cols
        : static_cast<std::size_t>(cv::countNonZero(mask_));
    component_count_ = pixels * static_cast<std::size_t>(prepared_.channels());
    if (component_count_ == 0) {
        throw std::invalid_argument("reference mask has no pixels");
    }
    key_ = detail::make_detector_key(
        "mean_absolute_similarity",
        roi_,
        std::to_string(component_count_),
        reference_
    );
}

DetectionResult MeanAbsoluteSimilarityDetector::detect(FrameContext& context) const {
    cv::Mat frame = detail::frame_region(context.frame().image, roi_);
    require_finite(frame, "mean absolute similarity");
    if (frame.size() != prepared_.size() || frame.channels() != prepared_.channels()) {
        throw std::invalid_argument("shape mismatch between frame and reference");
    }
    cv::Mat frame_float = to_float64(frame);
    cv::Mat difference;
    cv::subtract(frame_float, prepared_, difference);
    const double total = masked_sum(difference, mask_, false);
    const double error = total / static_cast<double>(component_count_);
    return DetectionResult{detail::clamp_unit(1.0 - error / 255.0)};
}

std::vector<ReferenceImage> MeanAbsoluteSimilarityDetector::reference_images() const {
    return {ReferenceImage{"reference", reference_.clone()}};
}

std::string MeanAbsoluteSimilarityDetector::describe() const {
    return "mean absolute similarity (" + detail::region_key(roi_) + ")";
}

RootMeanSquareSimilarityDetector::RootMeanSquareSimilarityDetector(
    cv::Mat reference,
    std::optional<Region> roi
)
    : reference_(reference.clone()), roi_(roi) {
    auto prepared = detail::prepare_reference_alpha(reference_);
    prepared_ = to_float64(prepared.image);
    mask_ = prepared.mask;
    const std::size_t pixels = mask_.empty()
        ? static_cast<std::size_t>(prepared_.rows) * prepared_.cols
        : static_cast<std::size_t>(cv::countNonZero(mask_));
    component_count_ = pixels * static_cast<std::size_t>(prepared_.channels());
    if (component_count_ == 0) {
        throw std::invalid_argument("reference mask has no pixels");
    }
    key_ = detail::make_detector_key(
        "root_mean_square_similarity",
        roi_,
        std::to_string(component_count_),
        reference_
    );
}

DetectionResult RootMeanSquareSimilarityDetector::detect(FrameContext& context) const {
    cv::Mat frame = detail::frame_region(context.frame().image, roi_);
    require_finite(frame, "root mean square similarity");
    if (frame.size() != prepared_.size() || frame.channels() != prepared_.channels()) {
        throw std::invalid_argument("shape mismatch between frame and reference");
    }
    cv::Mat frame_float = to_float64(frame);
    cv::Mat difference;
    cv::subtract(frame_float, prepared_, difference);
    const double total = masked_sum(difference, mask_, true);
    const double error =
        std::sqrt(total) / std::sqrt(static_cast<double>(component_count_));
    return DetectionResult{detail::clamp_unit(1.0 - error / 255.0)};
}

std::vector<ReferenceImage> RootMeanSquareSimilarityDetector::reference_images() const {
    return {ReferenceImage{"reference", reference_.clone()}};
}

std::string RootMeanSquareSimilarityDetector::describe() const {
    return "root mean square similarity (" + detail::region_key(roi_) + ")";
}

HistogramSimilarityDetector::HistogramSimilarityDetector(
    cv::Mat reference,
    std::optional<Region> roi
)
    : reference_(reference.clone()), roi_(roi) {
    if (reference_.depth() != CV_8U) {
        throw std::invalid_argument("reference must be an 8-bit image");
    }
    const auto prepared = detail::prepare_reference_alpha(reference_);
    require_bgr8(prepared.image);
    mask_ = prepared.mask;
    histogram_ = color_histogram(prepared.image, mask_);
    key_ = detail::make_detector_key("histogram_similarity", roi_, "v1", reference_);
}

DetectionResult HistogramSimilarityDetector::detect(FrameContext& context) const {
    const cv::Mat frame = detail::frame_region(context.frame().image, roi_);
    validate_masked_frame(frame, mask_);
    const double distance = cv::compareHist(
        histogram_, color_histogram(frame, mask_), cv::HISTCMP_BHATTACHARYYA
    );
    return DetectionResult{detail::clamp_unit(1.0 - distance)};
}

std::vector<ReferenceImage> HistogramSimilarityDetector::reference_images() const {
    return {ReferenceImage{"reference", reference_.clone()}};
}

std::string HistogramSimilarityDetector::describe() const {
    return "histogram similarity (" + detail::region_key(roi_) + ")";
}

PerceptualHashSimilarityDetector::PerceptualHashSimilarityDetector(
    cv::Mat reference,
    std::optional<Region> roi
)
    : reference_(reference.clone()), roi_(roi) {
    if (reference_.depth() != CV_8U) {
        throw std::invalid_argument("reference must be an 8-bit image");
    }
    const auto prepared = detail::prepare_reference_alpha(reference_);
    require_bgr8(prepared.image);
    mask_ = prepared.mask;
    reference_hash_ = perceptual_hash(prepared.image, mask_);
    key_ = detail::make_detector_key("perceptual_hash_similarity", roi_, "v1", reference_);
}

DetectionResult PerceptualHashSimilarityDetector::detect(FrameContext& context) const {
    const cv::Mat frame = detail::frame_region(context.frame().image, roi_);
    validate_masked_frame(frame, mask_);
    const double distance = cv::norm(reference_hash_, perceptual_hash(frame, mask_), cv::NORM_HAMMING);
    return DetectionResult{detail::clamp_unit(1.0 - distance / 64.0)};
}

std::vector<ReferenceImage> PerceptualHashSimilarityDetector::reference_images() const {
    return {ReferenceImage{"reference", reference_.clone()}};
}

std::string PerceptualHashSimilarityDetector::describe() const {
    return "perceptual hash similarity (" + detail::region_key(roi_) + ")";
}

DifferenceHashSimilarityDetector::DifferenceHashSimilarityDetector(
    cv::Mat reference,
    int hash_size,
    std::optional<Region> roi
)
    : reference_(reference.clone()), hash_size_(hash_size), roi_(roi) {
    if (hash_size_ <= 0) {
        throw std::invalid_argument("hash_size must be a positive integer");
    }
    auto prepared = detail::prepare_reference_alpha(reference_);
    reference_hash_ = detail::dhash_bits(detail::to_gray(prepared.image), hash_size_);
    key_ = detail::make_detector_key(
        "difference_hash_similarity",
        roi_,
        std::to_string(hash_size_),
        reference_
    );
}

DetectionResult DifferenceHashSimilarityDetector::detect(FrameContext& context) const {
    cv::Mat frame_hash = frame_dhash_cached(context, hash_size_, roi_);
    if (frame_hash.size() != reference_hash_.size()) {
        throw std::invalid_argument("difference hash size mismatch");
    }
    cv::Mat difference;
    cv::absdiff(frame_hash, reference_hash_, difference);
    const double different = cv::sum(difference)[0];
    const double denominator = static_cast<double>(hash_size_) * hash_size_;
    return DetectionResult{detail::clamp_unit(1.0 - different / denominator)};
}

std::vector<ReferenceImage> DifferenceHashSimilarityDetector::reference_images() const {
    return {ReferenceImage{"reference", reference_.clone()}};
}

std::string DifferenceHashSimilarityDetector::describe() const {
    return "difference hash (hash_size=" + std::to_string(hash_size_) + ')';
}

MeanBrightnessDetector::MeanBrightnessDetector(std::optional<Region> roi) : roi_(roi) {
    key_ = detail::make_detector_key("mean_brightness", roi_, "v1");
}

DetectionResult MeanBrightnessDetector::detect(FrameContext& context) const {
    cv::Mat frame = detail::frame_region(context.frame().image, roi_);
    require_finite(frame, "mean brightness");
    const cv::Scalar mean = cv::mean(frame);
    double sum = 0.0;
    for (int channel = 0; channel < frame.channels(); ++channel) {
        sum += mean[channel];
    }
    const double value = sum / static_cast<double>(frame.channels());
    return DetectionResult{detail::clamp_unit(value / 255.0)};
}

std::string MeanBrightnessDetector::describe() const {
    return "mean brightness (" + detail::region_key(roi_) + ")";
}

ColorRangeDetector::ColorRangeDetector(
    std::vector<double> lower,
    std::vector<double> upper,
    std::optional<Region> roi
)
    : lower_(std::move(lower)), upper_(std::move(upper)), roi_(roi) {
    if (lower_.size() != 1 && lower_.size() != 3) {
        throw std::invalid_argument("color bound length must be 1 or 3");
    }
    if (lower_.size() != upper_.size()) {
        throw std::invalid_argument("color bound length mismatch");
    }
    for (std::size_t index = 0; index < lower_.size(); ++index) {
        if (!std::isfinite(lower_[index]) || !std::isfinite(upper_[index])) {
            throw std::invalid_argument("color bounds must be finite");
        }
        if (lower_[index] > upper_[index]) {
            throw std::invalid_argument("lower bound exceeds upper bound");
        }
    }
    std::ostringstream extra;
    for (std::size_t index = 0; index < lower_.size(); ++index) {
        extra << sanitize_double(lower_[index]) << '/' << sanitize_double(upper_[index]) << ';';
    }
    key_ = detail::make_detector_key("color_range", roi_, extra.str());
}

DetectionResult ColorRangeDetector::detect(FrameContext& context) const {
    cv::Mat frame = detail::frame_region(context.frame().image, roi_);
    require_finite(frame, "color range");
    const int channels = channel_count(frame);
    if (channels != static_cast<int>(lower_.size())) {
        throw std::invalid_argument("frame channel count does not match color bounds");
    }
    const cv::Scalar lower{lower_[0], lower_.size() > 1 ? lower_[1] : 0.0,
                           lower_.size() > 2 ? lower_[2] : 0.0, 0.0};
    const cv::Scalar upper{upper_[0], upper_.size() > 1 ? upper_[1] : 0.0,
                           upper_.size() > 2 ? upper_[2] : 0.0, 0.0};
    cv::Mat mask;
    cv::inRange(frame, lower, upper, mask);
    const double ratio = static_cast<double>(cv::countNonZero(mask)) /
                         static_cast<double>(mask.rows * mask.cols);
    return DetectionResult{detail::clamp_unit(ratio)};
}

std::string ColorRangeDetector::describe() const {
    return "color range (" + detail::region_key(roi_) + ")";
}

PhaseCorrelationDetector::PhaseCorrelationDetector(cv::Mat reference, std::optional<Region> roi)
    : reference_(reference.clone()), roi_(roi) {
    auto prepared = detail::prepare_reference_alpha(reference_);
    reference_gray_ = detail::to_gray(prepared.image);
    key_ = detail::make_detector_key("phase_correlation", roi_, "v1", reference_);
}

DetectionResult PhaseCorrelationDetector::detect(FrameContext& context) const {
    cv::Mat frame = detail::frame_gray(context, roi_);
    if (frame.size() != reference_gray_.size()) {
        throw std::invalid_argument("shape mismatch between frame and reference");
    }
    double response = 0.0;
    cv::phaseCorrelate(frame, reference_gray_, cv::noArray(), &response);
    if (!std::isfinite(response)) {
        throw std::invalid_argument("phase correlation produced a non-finite response");
    }
    return DetectionResult{detail::clamp_unit(response)};
}

std::vector<ReferenceImage> PhaseCorrelationDetector::reference_images() const {
    return {ReferenceImage{"reference", reference_.clone()}};
}

std::string PhaseCorrelationDetector::describe() const {
    return "phase correlation (" + detail::region_key(roi_) + ")";
}

}  // namespace divergencesplitter
