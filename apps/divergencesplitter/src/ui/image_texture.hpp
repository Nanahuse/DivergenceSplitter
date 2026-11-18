#pragma once

#include <d3d11.h>
#include <wrl/client.h>

#include <opencv2/core.hpp>

namespace divergencesplitter::ui {

// Uploads a BGR/BGRA/gray frame into a dynamic D3D11 texture for ImGui.
class ImageTexture {
public:
    ImageTexture() = default;
    ~ImageTexture();
    ImageTexture(const ImageTexture&) = delete;
    ImageTexture& operator=(const ImageTexture&) = delete;

    bool update(ID3D11Device* device, ID3D11DeviceContext* context, const cv::Mat& image);
    void clear();

    [[nodiscard]] void* handle() const noexcept;
    [[nodiscard]] int width() const noexcept { return width_; }
    [[nodiscard]] int height() const noexcept { return height_; }
    [[nodiscard]] bool valid() const noexcept { return view_ != nullptr; }

private:
    void release();

    Microsoft::WRL::ComPtr<ID3D11Texture2D> texture_;
    Microsoft::WRL::ComPtr<ID3D11ShaderResourceView> view_;
    int width_{};
    int height_{};
};

}  // namespace divergencesplitter::ui
