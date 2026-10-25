#pragma once

#include <optional>
#include <string>
#include <vector>

#include "divergencesplitter/configuration/configuration.hpp"

namespace divergencesplitter {

struct CameraModeInfo {
    int width{};
    int height{};
    double fps{};
    std::string format;
    std::string subtype_guid;

    friend bool operator==(const CameraModeInfo&, const CameraModeInfo&) = default;
};

struct CameraDeviceInfo {
    CameraBackend backend{CameraBackend::media_foundation};
    int index{};
    std::string name;
    std::vector<CameraModeInfo> modes;
};

[[nodiscard]] std::vector<CameraDeviceInfo> list_camera_devices();
[[nodiscard]] std::vector<CameraDeviceInfo> list_camera_devices(CameraBackend backend);

[[nodiscard]] std::optional<CameraDeviceInfo> resolve_camera_device(
    const CameraDeviceConfiguration& configured,
    const std::vector<CameraDeviceInfo>& devices
);

[[nodiscard]] CameraModeInfo resolve_camera_mode(
    const CameraModeConfiguration& configured,
    const std::vector<CameraModeInfo>& modes
);

[[nodiscard]] std::optional<CameraModeInfo> try_resolve_camera_mode(
    const CameraModeConfiguration& configured,
    const std::vector<CameraModeInfo>& modes
);

}  // namespace divergencesplitter
