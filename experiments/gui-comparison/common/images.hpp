#pragma once
#include "mock.hpp"
#include <filesystem>
namespace comparison {
// Toolkit-free owned RGBA across the adapter boundary; OpenCV stays private.
Image reference_image(MockEngine& engine, NodeId detector);
void verify_opencv_stack();
void save_png(const Image& image, const std::filesystem::path& path);
}
