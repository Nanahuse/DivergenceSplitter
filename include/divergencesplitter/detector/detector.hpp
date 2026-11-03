#pragma once

#include <memory>
#include <string>
#include <string_view>
#include <vector>

#include "divergencesplitter/detector/types.hpp"
#include "divergencesplitter/frame.hpp"

namespace divergencesplitter {

class Detector {
public:
    virtual ~Detector() = default;

    [[nodiscard]] virtual std::string_view type_name() const noexcept = 0;
    [[nodiscard]] virtual std::string cache_key() const = 0;
    [[nodiscard]] virtual DetectionResult detect(FrameContext& context) const = 0;
    [[nodiscard]] virtual std::vector<ReferenceImage> reference_images() const { return {}; }
    [[nodiscard]] virtual std::string describe() const { return std::string{type_name()}; }
};

using DetectorPtr = std::shared_ptr<const Detector>;
using MutableDetectorPtr = std::shared_ptr<Detector>;

[[nodiscard]] DetectionResult detect_cached(FrameContext& context, const DetectorPtr& detector);

}  // namespace divergencesplitter
