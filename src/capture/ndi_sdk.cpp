#include "divergencesplitter/capture/ndi.hpp"
#include "divergencesplitter/capture/frame_source.hpp"

#include <windows.h>
#include <Processing.NDI.Lib.h>
#include <Processing.NDI.DynamicLoad.h>

#include <filesystem>
#include <optional>
#include <string>
#include <vector>

#include "divergencesplitter/text.hpp"

namespace divergencesplitter {
namespace {

struct LoadedRuntime {
    HMODULE module{};
    const NDIlib_v5* functions{};
    std::filesystem::path path;
};

struct LoadAttempt {
    std::optional<LoadedRuntime> runtime;
    bool found_file{};
    std::string error;
};

std::vector<std::filesystem::path> runtime_candidates() {
    std::vector<std::filesystem::path> result;
    const auto library = std::filesystem::path{NDILIB_LIBRARY_NAME};

    const auto add_environment = [&](const wchar_t* name) {
        const DWORD size = GetEnvironmentVariableW(name, nullptr, 0);
        if (size == 0) {
            return;
        }
        std::wstring value(size, L'\0');
        const DWORD written = GetEnvironmentVariableW(name, value.data(), size);
        if (written == 0 || written >= size) {
            return;
        }
        value.resize(written);
        if (!value.empty()) {
            result.push_back(std::filesystem::path{value} / library);
        }
    };
    add_environment(to_wide(NDILIB_REDIST_FOLDER).c_str());
    add_environment(L"NDI_RUNTIME_DIR_V5");

    const auto add_program_files = [&](const wchar_t* environment, const wchar_t* folder) {
        const DWORD size = GetEnvironmentVariableW(environment, nullptr, 0);
        if (size == 0) {
            return;
        }
        std::wstring value(size, L'\0');
        const DWORD written = GetEnvironmentVariableW(environment, value.data(), size);
        if (written == 0 || written >= size) {
            return;
        }
        value.resize(written);
        if (!value.empty()) {
            result.push_back(std::filesystem::path{value} / L"NDI" / folder / library);
        }
    };
    add_program_files(L"ProgramW6432", L"NDI 6 Runtime");
    add_program_files(L"ProgramW6432", L"NDI 5 Runtime");
    add_program_files(L"ProgramFiles", L"NDI 6 Runtime");
    add_program_files(L"ProgramFiles", L"NDI 5 Runtime");

    return result;
}

LoadAttempt load_runtime() {
    LoadAttempt attempt;
    for (const auto& candidate : runtime_candidates()) {
        std::error_code error;
        if (!std::filesystem::is_regular_file(candidate, error)) {
            continue;
        }
        attempt.found_file = true;
        const HMODULE module = LoadLibraryExW(
            candidate.c_str(),
            nullptr,
            LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR | LOAD_LIBRARY_SEARCH_SYSTEM32
        );
        if (module == nullptr) {
            attempt.error = "cannot load " + candidate.filename().string() +
                            " (Windows error " + std::to_string(GetLastError()) + ")";
            continue;
        }
        const auto load = reinterpret_cast<const NDIlib_v5* (*)()>(
            GetProcAddress(module, "NDIlib_v5_load")
        );
        if (load == nullptr) {
            FreeLibrary(module);
            attempt.error = "runtime does not expose NDIlib_v5_load";
            continue;
        }
        const NDIlib_v5* functions = load();
        if (functions == nullptr) {
            FreeLibrary(module);
            attempt.error = "NDIlib_v5_load returned no function table";
            continue;
        }
        attempt.runtime = LoadedRuntime{module, functions, candidate};
        return attempt;
    }
    return attempt;
}

NdiRuntimeStatus detect_runtime_status() {
    LoadAttempt attempt = load_runtime();
    if (!attempt.runtime.has_value()) {
        if (!attempt.found_file) {
            return {
                NdiAvailability::not_installed,
                "NDI Runtime was not found. Install NDI Runtime to enable NDI input.",
            };
        }
        return {
            NdiAvailability::failed,
            "NDI Runtime could not be loaded: " + attempt.error,
        };
    }
    LoadedRuntime runtime = std::move(*attempt.runtime);
    const bool initialized = runtime.functions->initialize();
    std::string version;
    if (initialized) {
        if (const char* text = runtime.functions->version(); text != nullptr) {
            version = text;
        }
        runtime.functions->destroy();
    }
    FreeLibrary(runtime.module);
    if (!initialized) {
        return {
            NdiAvailability::failed,
            "NDI Runtime was found but could not be initialized: " +
                runtime.path.string(),
        };
    }
    return {
        NdiAvailability::available,
        version.empty() ? "NDI Runtime is available." : "NDI Runtime " + version + " is available.",
    };
}

class SdkApi final : public NdiApi {
public:
    explicit SdkApi(LoadedRuntime runtime)
        : module_(runtime.module), functions_(runtime.functions) {}
    ~SdkApi() override {
        if (module_ != nullptr) {
            if (initialized_) {
                functions_->destroy();
            }
            FreeLibrary(module_);
        }
    }
    bool initialize() override {
        if (!functions_->initialize()) {
            return false;
        }
        initialized_ = true;
        return true;
    }
    void destroy() noexcept override {
        if (initialized_) {
            functions_->destroy();
            initialized_ = false;
        }
        if (module_ != nullptr) {
            FreeLibrary(module_);
            module_ = nullptr;
        }
    }
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
        const auto* values = functions_->find_get_current_sources(
            static_cast<NDIlib_find_instance_t>(finder),
            &count
        );
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
        buffers->type = api->recv_capture_v2(
            recv,
            &buffers->video,
            &buffers->audio,
            &buffers->metadata,
            timeout_ms
        );
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
    HMODULE module_{};
    const NDIlib_v5* functions_{};
    bool initialized_{};
};

}  // namespace

const NdiRuntimeStatus& ndi_runtime_status() noexcept {
    static const NdiRuntimeStatus status = [] {
        try {
            return detect_runtime_status();
        } catch (const std::exception& error) {
            return NdiRuntimeStatus{
                NdiAvailability::failed,
                std::string{"NDI Runtime detection failed: "} + error.what(),
            };
        } catch (...) {
            return NdiRuntimeStatus{
                NdiAvailability::failed,
                "NDI Runtime detection failed.",
            };
        }
    }();
    return status;
}

std::shared_ptr<NdiApi> make_ndi_sdk_api() {
    LoadAttempt attempt = load_runtime();
    if (!attempt.runtime.has_value()) {
        throw FrameSourceError(
            "NDI Runtime is unavailable: " + ndi_runtime_status().message,
            false
        );
    }
    return std::make_shared<SdkApi>(std::move(*attempt.runtime));
}

}  // namespace divergencesplitter
