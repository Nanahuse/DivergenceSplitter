#include "images.hpp"
#include <opencv2/core.hpp>
#include <opencv2/img_hash.hpp>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <opencv2/videoio.hpp>
#include <stdexcept>

namespace comparison {
namespace {
cv::Mat view(const Image& image) {
    return {int(image.height), int(image.width), CV_8UC4, const_cast<std::uint8_t*>(image.rgba.data())};
}
Image decode_reference(const Image& source) {
    cv::Mat bgr;
    cv::cvtColor(view(source), bgr, cv::COLOR_RGBA2BGR);
    std::vector<uchar> png;
    if (!cv::imencode(".png", bgr, png)) throw std::runtime_error("PNG encoding failed");
    auto decoded = cv::imdecode(png, cv::IMREAD_COLOR);
    cv::Mat rgba;
    cv::cvtColor(decoded, rgba, cv::COLOR_BGR2RGBA);
    Image result{std::uint32_t(rgba.cols), std::uint32_t(rgba.rows), {}};
    result.rgba.assign(rgba.data, rgba.data + rgba.total() * 4);
    return result;
}
}
Image reference_image(MockEngine& engine, NodeId detector, std::shared_ptr<const Topology> snapshot) {
    return decode_reference(engine.reference(detector, std::move(snapshot)));
}
void save_png(const Image& image, const std::filesystem::path& path) {
    cv::Mat bgr;
    cv::cvtColor(view(image), bgr, cv::COLOR_RGBA2BGR);
    if (!cv::imwrite(path.string(), bgr)) throw std::runtime_error("PNG write failed");
}
void verify_opencv_stack() {
    const auto directory = std::filesystem::temp_directory_path() /
        ("ds-gui-" + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
    std::filesystem::create_directory(directory);
    struct Cleanup {
        std::filesystem::path path;
        ~Cleanup() {
            std::error_code ignored;
            std::filesystem::remove(path / "test.png", ignored);
            std::filesystem::remove(path / "test.avi", ignored);
            std::filesystem::remove(path, ignored);
        }
    } cleanup{directory};
    cv::Mat image(36, 64, CV_8UC3, cv::Scalar(20, 80, 120));
    cv::Mat processed;
    cv::GaussianBlur(image, processed, {3, 3}, 0);
    if (!cv::imwrite((directory / "test.png").string(), processed)) throw std::runtime_error("PNG save failed");
    auto loaded = cv::imread((directory / "test.png").string());
    cv::Mat hash;
    cv::img_hash::PHash::create()->compute(loaded, hash);
    if (hash.empty()) throw std::runtime_error("PHash failed");
    {
        cv::VideoWriter writer((directory / "test.avi").string(), cv::CAP_OPENCV_MJPEG,
            cv::VideoWriter::fourcc('M', 'J', 'P', 'G'), 60.0, {64, 36});
        if (!writer.isOpened()) throw std::runtime_error("MJPEG writer failed");
        for (int frame = 0; frame < 3; ++frame) writer.write(image);
    }
    cv::VideoCapture capture((directory / "test.avi").string(), cv::CAP_OPENCV_MJPEG);
    cv::Mat frame;
    int frames = 0;
    while (capture.read(frame)) ++frames;
    capture.release();
    if (frames != 3) throw std::runtime_error("MJPEG reader failed");
}
}
