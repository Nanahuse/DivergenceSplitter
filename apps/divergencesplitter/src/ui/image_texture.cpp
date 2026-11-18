#include "image_texture.hpp"

#include <opencv2/imgproc.hpp>

#include <algorithm>
#include <cstdint>

namespace divergencesplitter::ui {
namespace {

cv::Mat to_rgba8(const cv::Mat& image) {
    cv::Mat converted;
    if (image.depth() != CV_8U) {
        double minimum = 0.0;
        double maximum = 0.0;
        cv::minMaxLoc(image.reshape(1), &minimum, &maximum);
        const double scale = maximum > minimum ? 255.0 / (maximum - minimum) : 1.0;
        image.convertTo(converted, CV_8U, scale, -minimum * scale);
    } else {
        converted = image;
    }

    cv::Mat rgba;
    if (converted.channels() == 1) {
        cv::cvtColor(converted, rgba, cv::COLOR_GRAY2RGBA);
    } else if (converted.channels() == 3) {
        cv::cvtColor(converted, rgba, cv::COLOR_BGR2RGBA);
    } else if (converted.channels() == 4) {
        cv::cvtColor(converted, rgba, cv::COLOR_BGRA2RGBA);
    }
    return rgba;
}

}  // namespace

ImageTexture::~ImageTexture() {
    release();
}

void ImageTexture::release() {
    view_.Reset();
    texture_.Reset();
    width_ = 0;
    height_ = 0;
}

void ImageTexture::clear() {
    release();
}

bool ImageTexture::update(
    ID3D11Device* device,
    ID3D11DeviceContext* context,
    const cv::Mat& image
) {
    if (device == nullptr || context == nullptr || image.empty()) {
        clear();
        return false;
    }
    const cv::Mat rgba = to_rgba8(image);
    if (rgba.empty()) {
        clear();
        return false;
    }
    if (!texture_ || rgba.cols != width_ || rgba.rows != height_) {
        release();
        D3D11_TEXTURE2D_DESC description{};
        description.Width = static_cast<UINT>(rgba.cols);
        description.Height = static_cast<UINT>(rgba.rows);
        description.MipLevels = 1;
        description.ArraySize = 1;
        description.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        description.SampleDesc.Count = 1;
        description.Usage = D3D11_USAGE_DYNAMIC;
        description.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        description.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
        if (FAILED(device->CreateTexture2D(&description, nullptr, &texture_))) {
            release();
            return false;
        }
        D3D11_SHADER_RESOURCE_VIEW_DESC view_description{};
        view_description.Format = description.Format;
        view_description.ViewDimension = D3D11_SRV_DIMENSION_TEXTURE2D;
        view_description.Texture2D.MipLevels = 1;
        if (FAILED(device->CreateShaderResourceView(
                texture_.Get(),
                &view_description,
                &view_
            ))) {
            release();
            return false;
        }
        width_ = rgba.cols;
        height_ = rgba.rows;
    }

    D3D11_MAPPED_SUBRESOURCE mapped{};
    if (FAILED(context->Map(texture_.Get(), 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped))) {
        clear();
        return false;
    }
    const auto* source = rgba.ptr<std::uint8_t>();
    auto* destination = static_cast<std::uint8_t*>(mapped.pData);
    const std::size_t row_bytes = static_cast<std::size_t>(rgba.cols) * 4;
    for (int row = 0; row < rgba.rows; ++row) {
        std::copy_n(
            source + static_cast<std::size_t>(row) * rgba.step,
            row_bytes,
            destination + static_cast<std::size_t>(row) * mapped.RowPitch
        );
    }
    context->Unmap(texture_.Get(), 0);
    return true;
}

void* ImageTexture::handle() const noexcept {
    return view_.Get();
}

}  // namespace divergencesplitter::ui
