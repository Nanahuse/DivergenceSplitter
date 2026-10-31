#include "divergencesplitter/capture/ndi.hpp"
#include "divergencesplitter/capture/frame_source.hpp"

#if DIVERGENCESPLITTER_ENABLE_NDI
#include <windows.h>
#include <Processing.NDI.Lib.h>
#include <Processing.NDI.DynamicLoad.h>

#include <filesystem>
#include <vector>

namespace divergencesplitter {
namespace {

// Application-local loading is deliberate: the ZIP must work without a global
// runtime installation, PATH entry, SDK installation, or current-directory DLL.
class SdkApi final : public NdiApi {
public:
    SdkApi() {
        std::vector<wchar_t> path(32768);
        const auto length = GetModuleFileNameW(nullptr, path.data(), static_cast<DWORD>(path.size()));
        if (length == 0 || length >= path.size()) fail("cannot locate application directory");
        const auto dll = std::filesystem::path{std::wstring{path.data(), length}}.parent_path() /
            L"Processing.NDI.Lib.x64.dll";
        module_ = LoadLibraryExW(dll.c_str(), nullptr,
            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32);
        if (!module_) fail("cannot load application-local Processing.NDI.Lib.x64.dll (Windows error " +
            std::to_string(GetLastError()) + ")");
        const auto load = reinterpret_cast<const NDIlib_v5* (*)()>(GetProcAddress(module_, "NDIlib_v5_load"));
        if (load) functions_ = load();
        if (!functions_) {
            FreeLibrary(module_);
            module_ = nullptr;
            fail("runtime does not expose the official NDIlib_v5_load function table");
        }
    }
    ~SdkApi() override { if (module_) FreeLibrary(module_); }
    bool initialize() override { return functions_->initialize(); }
    void destroy() noexcept override { functions_->destroy(); }
    std::string version() const override { return functions_->version(); }
    Handle create_finder() override {
        NDIlib_find_create_t settings;
        settings.show_local_sources = true;
        return functions_->find_create_v2(&settings);
    }
    void destroy_finder(Handle finder) noexcept override {
        functions_->find_destroy(static_cast<NDIlib_find_instance_t>(finder));
    }
    void wait_for_sources(Handle finder, std::uint32_t timeout_ms) override {
        functions_->find_wait_for_sources(static_cast<NDIlib_find_instance_t>(finder), timeout_ms);
    }
    std::vector<std::string> sources(Handle finder) override {
        std::uint32_t count{};
        const auto* values = functions_->find_get_current_sources(static_cast<NDIlib_find_instance_t>(finder), &count);
        std::vector<std::string> result;
        for (std::uint32_t i = 0; values && i < count; ++i) {
            if (values[i].p_ndi_name) result.emplace_back(values[i].p_ndi_name);
        }
        return result;
    }
    Handle create_receiver(const std::string& name) override {
        NDIlib_recv_create_v3_t settings;
        // Explicit 8-bit format and deinterlacing avoid fastest-mode single
        // fields / high-bit-depth formats that the image pipeline cannot use.
        settings.color_format = NDIlib_recv_color_format_BGRX_BGRA;
        settings.bandwidth = NDIlib_recv_bandwidth_highest;
        settings.allow_video_fields = false;
        settings.source_to_connect_to.p_ndi_name = name.c_str();
        settings.source_to_connect_to.p_url_address = nullptr;
        settings.p_ndi_recv_name = "DivergenceSplitter";
        return functions_->recv_create_v3(&settings);
    }
    void destroy_receiver(Handle receiver) noexcept override {
        functions_->recv_destroy(static_cast<NDIlib_recv_instance_t>(receiver));
    }
    NdiCapturedFrame capture(Handle receiver, std::uint32_t timeout_ms) override {
        struct Buffers {
            NDIlib_video_frame_v2_t video{};
            NDIlib_audio_frame_v2_t audio{};
            NDIlib_metadata_frame_t metadata{};
            NDIlib_frame_type_e type{NDIlib_frame_type_none};
        };
        const auto recv = static_cast<NDIlib_recv_instance_t>(receiver);
        const auto* api = functions_;
        auto buffers = std::shared_ptr<Buffers>(new Buffers, [api, recv](Buffers* frame) {
            switch (frame->type) {
                case NDIlib_frame_type_video: api->recv_free_video_v2(recv, &frame->video); break;
                case NDIlib_frame_type_audio: api->recv_free_audio_v2(recv, &frame->audio); break;
                case NDIlib_frame_type_metadata: api->recv_free_metadata(recv, &frame->metadata); break;
                default: break;
            }
            delete frame;
        });
        buffers->type = api->recv_capture_v2(recv, &buffers->video, &buffers->audio, &buffers->metadata, timeout_ms);
        NdiCapturedFrame result;
        result.lease = buffers;
        switch (buffers->type) {
            case NDIlib_frame_type_video: result.type = NdiFrameType::video; break;
            case NDIlib_frame_type_audio: result.type = NdiFrameType::audio; break;
            case NDIlib_frame_type_metadata: result.type = NdiFrameType::metadata; break;
            case NDIlib_frame_type_status_change: result.type = NdiFrameType::status_change; break;
            case NDIlib_frame_type_error: result.type = NdiFrameType::error; break;
            default: result.type = NdiFrameType::none; break;
        }
        NdiPixelFormat format = NdiPixelFormat::unsupported;
        switch (buffers->video.FourCC) {
            case NDIlib_FourCC_video_type_UYVY: format = NdiPixelFormat::uyvy; break;
            case NDIlib_FourCC_video_type_UYVA: format = NdiPixelFormat::uyva; break;
            case NDIlib_FourCC_video_type_BGRA: format = NdiPixelFormat::bgra; break;
            case NDIlib_FourCC_video_type_BGRX: format = NdiPixelFormat::bgrx; break;
            case NDIlib_FourCC_video_type_RGBA: format = NdiPixelFormat::rgba; break;
            case NDIlib_FourCC_video_type_RGBX: format = NdiPixelFormat::rgbx; break;
            default: break;
        }
        const auto& video = buffers->video;
        result.video = {video.xres, video.yres, video.line_stride_in_bytes, format, video.p_data};
        return result;
    }

private:
    [[noreturn]] static void fail(const std::string& message) {
        throw FrameSourceError("NDI SDK: " + message, false);
    }
    HMODULE module_{};
    const NDIlib_v5* functions_{};
};
}  // namespace

std::shared_ptr<NdiApi> make_ndi_sdk_api() { return std::make_shared<SdkApi>(); }
}  // namespace divergencesplitter
#else
namespace divergencesplitter {
std::shared_ptr<NdiApi> make_ndi_sdk_api() {
    throw FrameSourceError("NDI input is not available in this build. Enable DIVERGENCESPLITTER_ENABLE_NDI.", false);
}
}  // namespace divergencesplitter
#endif
