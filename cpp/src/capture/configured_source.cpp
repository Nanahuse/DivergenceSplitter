#include "divergencesplitter/capture/configured_source.hpp"

#include <opencv2/videoio.hpp>
#include <variant>
#include "divergencesplitter/capture/camera_devices.hpp"

namespace divergencesplitter {

std::unique_ptr<FrameSource> create_frame_source(
    const SourceConfiguration& source
) {
    return std::visit(
        [](const auto& value) -> std::unique_ptr<FrameSource> {
            using Value = std::decay_t<decltype(value)>;
            if constexpr (std::is_same_v<Value, CameraSourceConfiguration>) {
                const auto devices = list_camera_devices();
                const auto device = resolve_camera_device(value.device, devices);
                if (!device.has_value()) {
                    throw ConfigurationError(
                        "camera device is not connected: backend=" +
                        std::string{to_string(value.device.backend)} + ", name=" +
                        value.device.name + ", index=" + std::to_string(value.device.index)
                    );
                }
                const auto mode = resolve_camera_mode(value.mode, device->modes);
                if (device->backend == CameraBackend::direct_show &&
                    !mode.subtype_selectable) {
                    throw ConfigurationError(
                        "DirectShow/OpenCV cannot select this camera subtype exactly: " +
                        mode.subtype_guid + ". Choose a compressed mode or use Media Foundation."
                    );
                }
                CameraSourceOptions options;
                options.device_index = device->index;
                options.backend = device->backend == CameraBackend::direct_show
                    ? cv::CAP_DSHOW
                    : cv::CAP_MSMF;
                options.width = mode.width;
                options.height = mode.height;
                options.fps = mode.fps;
                options.subtype_guid = mode.subtype_guid;
                options.enforce_mode = true;
                options.request_60_fps = value.request_60_fps;
                return std::make_unique<CameraFrameSource>(options);
            } else if constexpr (std::is_same_v<Value, VideoSourceConfiguration>) {
                return std::make_unique<VideoFileFrameSource>(
                    VideoFileSourceOptions{value.path}
                );
            } else {
                return std::make_unique<NdiFrameSource>(NdiSourceOptions{value.name});
            }
        },
        source
    );
}

FrameNormalizer create_frame_normalizer(const TransformConfiguration& transform) {
    std::optional<CropMargins> crop;
    if (transform.crop.has_value()) {
        crop = CropMargins{
            transform.crop->left,
            transform.crop->right,
            transform.crop->top,
            transform.crop->bottom,
        };
    }
    std::optional<OutputSize> resize;
    if (transform.resize.has_value()) {
        resize = OutputSize{transform.resize->width, transform.resize->height};
    }
    const auto interpolation = transform.resize.has_value()
        ? transform.resize->interpolation
        : ResizeInterpolation::area;
    return FrameNormalizer{crop, resize, interpolation};
}

}  // namespace divergencesplitter
