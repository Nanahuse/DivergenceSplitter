#include <gtest/gtest.h>

#include <vector>

#include "divergencesplitter/capture/camera_devices.hpp"

using namespace divergencesplitter;

namespace {

CameraDeviceInfo device(
    CameraBackend backend,
    int index,
    std::string name,
    std::vector<CameraModeInfo> modes = {}
) {
    return CameraDeviceInfo{backend, index, std::move(name), std::move(modes)};
}

}  // namespace

TEST(CameraDevices, ResolvesByBackendAndName) {
    const std::vector<CameraDeviceInfo> devices{
        device(CameraBackend::direct_show, 0, "Camera A"),
        device(CameraBackend::media_foundation, 0, "Camera A"),
        device(CameraBackend::media_foundation, 1, "Camera B"),
    };
    const auto resolved = resolve_camera_device(
        CameraDeviceConfiguration{CameraBackend::media_foundation, "Camera B", 0},
        devices
    );
    ASSERT_TRUE(resolved.has_value());
    EXPECT_EQ(resolved->name, "Camera B");
    EXPECT_EQ(resolved->backend, CameraBackend::media_foundation);
}

TEST(CameraDevices, UsesIndexOnlyForDuplicateNames) {
    const std::vector<CameraDeviceInfo> devices{
        device(CameraBackend::media_foundation, 4, "Duplicate"),
        device(CameraBackend::media_foundation, 7, "Duplicate"),
    };
    const auto resolved = resolve_camera_device(
        CameraDeviceConfiguration{CameraBackend::media_foundation, "Duplicate", 7},
        devices
    );
    ASSERT_TRUE(resolved.has_value());
    EXPECT_EQ(resolved->index, 7);

    EXPECT_FALSE(resolve_camera_device(
        CameraDeviceConfiguration{CameraBackend::media_foundation, "Duplicate", 9},
        devices
    ).has_value());
}

TEST(CameraDevices, RejectsMissingDevice) {
    const std::vector<CameraDeviceInfo> devices{
        device(CameraBackend::direct_show, 0, "Camera A"),
    };
    EXPECT_FALSE(resolve_camera_device(
        CameraDeviceConfiguration{CameraBackend::media_foundation, "Camera A", 0},
        devices
    ).has_value());
}

TEST(CameraDevices, ResolvesExactModeWithFpsTolerance) {
    const std::vector<CameraModeInfo> modes{
        CameraModeInfo{1920, 1080, 59.9400599, "MJPG", "47504A4D-0000-0010-8000-00AA00389B71"},
        CameraModeInfo{1280, 720, 30.0, "NV12", "3231564E-0000-0010-8000-00AA00389B71"},
    };
    const CameraModeConfiguration configured{
        1920,
        1080,
        59.94006,
        "47504A4D-0000-0010-8000-00AA00389B71",
    };
    const auto mode = resolve_camera_mode(configured, modes);
    EXPECT_EQ(mode.width, 1920);
    EXPECT_EQ(mode.height, 1080);
    EXPECT_NEAR(mode.fps, 59.9400599, 1e-6);
}

TEST(CameraDevices, RejectsUnavailableMode) {
    const std::vector<CameraModeInfo> modes{
        CameraModeInfo{1280, 720, 30.0, "NV12", "3231564E-0000-0010-8000-00AA00389B71"},
    };
    const CameraModeConfiguration configured{
        1920,
        1080,
        60.0,
        "47504A4D-0000-0010-8000-00AA00389B71",
    };
    EXPECT_THROW((void)resolve_camera_mode(configured, modes), ConfigurationError);
}

TEST(CameraDevices, EnumerationDoesNotThrow) {
    EXPECT_NO_THROW((void)list_camera_devices());
}
