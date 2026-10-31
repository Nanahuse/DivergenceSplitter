#pragma once

#include "divergencesplitter/capture/frame_source.hpp"
#include "divergencesplitter/configuration/configuration.hpp"

namespace divergencesplitter {

// Call on a capture worker: camera enumeration and device creation may block.
[[nodiscard]] std::unique_ptr<FrameSource> create_frame_source(const SourceConfiguration& source);
[[nodiscard]] FrameNormalizer create_frame_normalizer(const TransformConfiguration& transform);

}  // namespace divergencesplitter
