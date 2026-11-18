#include "divergencesplitter/capture/source_configuration.hpp"

namespace divergencesplitter {

std::string_view to_string(CameraBackend backend) noexcept {
    switch (backend) {
        case CameraBackend::direct_show:
            return "direct_show";
        case CameraBackend::media_foundation:
            return "media_foundation";
    }
    return "media_foundation";
}

std::optional<CameraBackend> parse_camera_backend(std::string_view value) noexcept {
    if (value == "direct_show") {
        return CameraBackend::direct_show;
    }
    if (value == "media_foundation") {
        return CameraBackend::media_foundation;
    }
    return std::nullopt;
}

}  // namespace divergencesplitter
