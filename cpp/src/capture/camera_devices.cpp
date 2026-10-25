// Camera enumeration adapted from Nanahuse/windows-capture-device-list v0.2.0
// (MIT License). See licenses/windows-capture-device-list.txt.

#include "divergencesplitter/capture/camera_devices.hpp"

#include <algorithm>
#include <cmath>
#include <cwctype>
#include <functional>
#include <iterator>
#include <stack>
#include <string>
#include <vector>

#include "divergencesplitter/configuration/configuration.hpp"

#ifdef _WIN32
#include <windows.h>
#include <dshow.h>
#include <dvdmedia.h>
#include <ks.h>
#include <ksmedia.h>
#include <mfapi.h>
#include <mferror.h>
#include <mfidl.h>
#include <mfreadwrite.h>
#endif

namespace divergencesplitter {
namespace {

class ScopeGuard {
public:
    ~ScopeGuard() noexcept {
        while (!functions_.empty()) {
            functions_.top()();
            functions_.pop();
        }
    }

    void add(std::function<void()> func) {
        functions_.push(std::move(func));
    }

    template <typename T>
    void add_release(T* pointer) {
        functions_.push([pointer]() {
            if (pointer != nullptr) {
                pointer->Release();
            }
        });
    }

private:
    std::stack<std::function<void()>> functions_;
};

#ifdef _WIN32
constexpr GUID kFourccTail = {0, 0x0000, 0x0010, {0x80, 0x00, 0x00, 0xaa, 0x00, 0x38, 0x9b, 0x71}};

bool equal_guid_tail(const GUID& guid) {
    return guid.Data2 == kFourccTail.Data2 && guid.Data3 == kFourccTail.Data3 &&
           std::equal(std::begin(guid.Data4), std::end(guid.Data4), std::begin(kFourccTail.Data4));
}

std::string guid_string(const GUID& guid) {
    wchar_t buffer[40]{};
    if (StringFromGUID2(guid, buffer, static_cast<int>(std::size(buffer))) == 0) {
        return {};
    }
    std::wstring value(buffer);
    if (value.size() >= 2 && value.front() == L'{' && value.back() == L'}') {
        value = value.substr(1, value.size() - 2);
    }
    std::string result;
    result.reserve(value.size());
    for (wchar_t character : value) {
        result.push_back(static_cast<char>(std::towupper(character)));
    }
    return result;
}

std::string format_from_guid(const GUID& guid) {
    if (equal_guid_tail(guid)) {
        std::string fourcc;
        for (int shift = 0; shift < 32; shift += 8) {
            const char character = static_cast<char>((guid.Data1 >> shift) & 0xff);
            if (character < 0x20 || character > 0x7e) {
                return {};
            }
            fourcc.push_back(character);
        }
        return fourcc;
    }
    if (IsEqualGUID(guid, MEDIASUBTYPE_RGB24)) {
        return "RGB24";
    }
    if (IsEqualGUID(guid, MEDIASUBTYPE_RGB32)) {
        return "RGB32";
    }
    if (IsEqualGUID(guid, MFVideoFormat_NV12)) {
        return "NV12";
    }
    return {};
}

CameraModeInfo make_mode(int width, int height, double fps, const GUID& subtype) {
    CameraModeInfo mode;
    mode.width = width;
    mode.height = height;
    mode.fps = fps;
    mode.subtype_guid = guid_string(subtype);
    mode.format = format_from_guid(subtype);
    return mode;
}

void deduplicate_modes(std::vector<CameraModeInfo>& modes) {
    std::vector<CameraModeInfo> unique;
    for (const auto& mode : modes) {
        const bool duplicate = std::any_of(
            unique.begin(),
            unique.end(),
            [&](const CameraModeInfo& other) {
                return mode.width == other.width && mode.height == other.height &&
                       mode.fps == other.fps && mode.subtype_guid == other.subtype_guid;
            }
        );
        if (!duplicate) {
            unique.push_back(mode);
        }
    }
    modes = std::move(unique);
}

std::string property_string(IPropertyBag* bag, LPCWSTR property) {
    VARIANT value;
    VariantInit(&value);
    if (FAILED(bag->Read(property, &value, nullptr))) {
        VariantClear(&value);
        return "Unknown";
    }
    ScopeGuard guard;
    guard.add([&] { VariantClear(&value); });
    if (value.vt != VT_BSTR || value.bstrVal == nullptr) {
        return "Unknown";
    }
    const int size = WideCharToMultiByte(
        CP_UTF8,
        0,
        value.bstrVal,
        -1,
        nullptr,
        0,
        nullptr,
        nullptr
    );
    std::string result(size > 0 ? size - 1 : 0, '\0');
    if (size > 1) {
        WideCharToMultiByte(
            CP_UTF8,
            0,
            value.bstrVal,
            -1,
            &result[0],
            size - 1,
            nullptr,
            nullptr
        );
    }
    return result;
}

std::string device_name(IMoniker* moniker) {
    IPropertyBag* bag = nullptr;
    if (FAILED(moniker->BindToStorage(nullptr, nullptr, IID_PPV_ARGS(&bag)))) {
        return "Unknown";
    }
    ScopeGuard guard;
    guard.add_release(bag);
    return property_string(bag, L"FriendlyName");
}

void free_media_type(AM_MEDIA_TYPE* media_type) {
    if (media_type == nullptr) {
        return;
    }
    if (media_type->cbFormat != 0) {
        CoTaskMemFree(media_type->pbFormat);
    }
    if (media_type->pUnk != nullptr) {
        media_type->pUnk->Release();
    }
    CoTaskMemFree(media_type);
}

bool pin_category(IPin* pin, const GUID& category) {
    IKsPropertySet* properties = nullptr;
    if (FAILED(pin->QueryInterface(IID_PPV_ARGS(&properties)))) {
        return false;
    }
    ScopeGuard guard;
    guard.add_release(properties);
    GUID value{};
    DWORD returned = 0;
    return SUCCEEDED(properties->Get(
               AMPROPSETID_Pin,
               AMPROPERTY_PIN_CATEGORY,
               nullptr,
               0,
               &value,
               sizeof(value),
               &returned
           )) &&
           IsEqualGUID(value, category);
}

IAMStreamConfig* stream_config_for_filter(IBaseFilter* filter) {
    IEnumPins* pins = nullptr;
    if (FAILED(filter->EnumPins(&pins))) {
        return nullptr;
    }
    ScopeGuard pins_guard;
    pins_guard.add_release(pins);
    IPin* capture_pin = nullptr;
    IPin* preview_pin = nullptr;
    IPin* pin = nullptr;
    while (pins->Next(1, &pin, nullptr) == S_OK) {
        ScopeGuard pin_guard;
        pin_guard.add_release(pin);
        IAMStreamConfig* config = nullptr;
        if (FAILED(pin->QueryInterface(IID_PPV_ARGS(&config)))) {
            continue;
        }
        if (pin_category(pin, PIN_CATEGORY_PREVIEW)) {
            if (preview_pin != nullptr) {
                preview_pin->Release();
            }
            preview_pin = pin;
            preview_pin->AddRef();
        } else if (pin_category(pin, PIN_CATEGORY_CAPTURE) && capture_pin == nullptr) {
            capture_pin = pin;
            capture_pin->AddRef();
        }
        config->Release();
    }

    IPin* selected = preview_pin != nullptr ? preview_pin : capture_pin;
    IAMStreamConfig* result = nullptr;
    if (selected != nullptr) {
        selected->QueryInterface(IID_PPV_ARGS(&result));
    }
    if (preview_pin != nullptr) {
        preview_pin->Release();
    }
    if (capture_pin != nullptr) {
        capture_pin->Release();
    }
    return result;
}

std::vector<CameraModeInfo> direct_show_modes(IMoniker* moniker) {
    IBaseFilter* filter = nullptr;
    if (FAILED(moniker->BindToObject(nullptr, nullptr, IID_PPV_ARGS(&filter)))) {
        return {};
    }
    ScopeGuard filter_guard;
    filter_guard.add_release(filter);
    IAMStreamConfig* config = stream_config_for_filter(filter);
    if (config == nullptr) {
        return {};
    }
    ScopeGuard config_guard;
    config_guard.add_release(config);

    int count = 0;
    int size = 0;
    if (FAILED(config->GetNumberOfCapabilities(&count, &size)) || size <= 0) {
        return {};
    }
    std::vector<CameraModeInfo> modes;
    for (int index = 0; index < count; ++index) {
        AM_MEDIA_TYPE* media_type = nullptr;
        std::vector<BYTE> caps(static_cast<size_t>(size));
        if (FAILED(config->GetStreamCaps(index, &media_type, caps.data()))) {
            continue;
        }
        ScopeGuard media_guard;
        media_guard.add([&] { free_media_type(media_type); });
        if (media_type == nullptr || media_type->pbFormat == nullptr) {
            continue;
        }

        LONG width = 0;
        LONG height = 0;
        REFERENCE_TIME frame_time = 0;
        if (IsEqualGUID(media_type->formattype, FORMAT_VideoInfo) &&
            media_type->cbFormat >= sizeof(VIDEOINFOHEADER)) {
            auto* info = reinterpret_cast<VIDEOINFOHEADER*>(media_type->pbFormat);
            width = info->bmiHeader.biWidth;
            height = info->bmiHeader.biHeight;
            frame_time = info->AvgTimePerFrame;
        } else if (IsEqualGUID(media_type->formattype, FORMAT_VideoInfo2) &&
                   media_type->cbFormat >= sizeof(VIDEOINFOHEADER2)) {
            auto* info = reinterpret_cast<VIDEOINFOHEADER2*>(media_type->pbFormat);
            width = info->bmiHeader.biWidth;
            height = info->bmiHeader.biHeight;
            frame_time = info->AvgTimePerFrame;
        } else {
            continue;
        }
        if (width <= 0 || height == 0 || frame_time <= 0) {
            continue;
        }
        modes.push_back(make_mode(
            width,
            std::abs(height),
            10000000.0 / static_cast<double>(frame_time),
            media_type->subtype
        ));
    }
    deduplicate_modes(modes);
    return modes;
}

std::vector<CameraDeviceInfo> enumerate_direct_show() {
    HRESULT initialized = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(initialized) && initialized != RPC_E_CHANGED_MODE) {
        return {};
    }
    ScopeGuard com_guard;
    if (SUCCEEDED(initialized)) {
        com_guard.add(&CoUninitialize);
    }

    ICreateDevEnum* device_enum = nullptr;
    if (FAILED(CoCreateInstance(
            CLSID_SystemDeviceEnum,
            nullptr,
            CLSCTX_INPROC_SERVER,
            IID_PPV_ARGS(&device_enum)
        ))) {
        return {};
    }
    ScopeGuard enum_guard;
    enum_guard.add_release(device_enum);
    IEnumMoniker* monikers = nullptr;
    if (device_enum->CreateClassEnumerator(CLSID_VideoInputDeviceCategory, &monikers, 0) != S_OK) {
        return {};
    }
    ScopeGuard moniker_guard;
    moniker_guard.add_release(monikers);

    std::vector<CameraDeviceInfo> devices;
    IMoniker* moniker = nullptr;
    while (monikers->Next(1, &moniker, nullptr) == S_OK) {
        ScopeGuard guard;
        guard.add_release(moniker);
        auto modes = direct_show_modes(moniker);
        devices.push_back(CameraDeviceInfo{
            CameraBackend::direct_show,
            static_cast<int>(devices.size()),
            device_name(moniker),
            std::move(modes),
        });
    }
    return devices;
}

bool get_size(IMFMediaType* type, UINT32& width, UINT32& height) {
    UINT64 value = 0;
    if (FAILED(type->GetUINT64(MF_MT_FRAME_SIZE, &value))) {
        return false;
    }
    width = static_cast<UINT32>(value >> 32);
    height = static_cast<UINT32>(value & 0xffffffff);
    return width > 0 && height > 0;
}

std::vector<CameraModeInfo> media_foundation_modes(IMFActivate* activate) {
    IMFMediaSource* source = nullptr;
    if (FAILED(activate->ActivateObject(IID_PPV_ARGS(&source)))) {
        return {};
    }
    ScopeGuard source_guard;
    source_guard.add_release(source);
    source_guard.add([source] { source->Shutdown(); });
    IMFSourceReader* reader = nullptr;
    if (FAILED(MFCreateSourceReaderFromMediaSource(source, nullptr, &reader))) {
        return {};
    }
    ScopeGuard reader_guard;
    reader_guard.add_release(reader);

    std::vector<CameraModeInfo> modes;
    for (DWORD stream = 0;; ++stream) {
        bool found_stream = false;
        for (DWORD index = 0;; ++index) {
            IMFMediaType* type = nullptr;
            HRESULT result = reader->GetNativeMediaType(stream, index, &type);
            if (result == MF_E_NO_MORE_TYPES || result == MF_E_INVALIDSTREAMNUMBER) {
                break;
            }
            if (FAILED(result)) {
                break;
            }
            found_stream = true;
            ScopeGuard type_guard;
            type_guard.add_release(type);
            GUID major{};
            GUID subtype{};
            UINT32 numerator = 0;
            UINT32 denominator = 0;
            UINT32 width = 0;
            UINT32 height = 0;
            if (FAILED(type->GetGUID(MF_MT_MAJOR_TYPE, &major)) ||
                !IsEqualGUID(major, MFMediaType_Video) ||
                FAILED(type->GetGUID(MF_MT_SUBTYPE, &subtype)) ||
                !get_size(type, width, height) ||
                FAILED(MFGetAttributeRatio(type, MF_MT_FRAME_RATE, &numerator, &denominator)) ||
                denominator == 0) {
                continue;
            }
            modes.push_back(make_mode(
                static_cast<int>(width),
                static_cast<int>(height),
                static_cast<double>(numerator) / static_cast<double>(denominator),
                subtype
            ));
        }
        if (!found_stream && stream > 0) {
            break;
        }
    }
    deduplicate_modes(modes);
    return modes;
}

std::string activate_name(IMFActivate* activate) {
    WCHAR* value = nullptr;
    UINT32 length = 0;
    if (FAILED(activate->GetAllocatedString(
            MF_DEVSOURCE_ATTRIBUTE_FRIENDLY_NAME,
            &value,
            &length
        ))) {
        return "Unknown";
    }
    ScopeGuard guard;
    guard.add([&] { CoTaskMemFree(value); });
    const int size = WideCharToMultiByte(
        CP_UTF8,
        0,
        value,
        static_cast<int>(length),
        nullptr,
        0,
        nullptr,
        nullptr
    );
    std::string result(size, '\0');
    if (size > 0) {
        WideCharToMultiByte(
            CP_UTF8,
            0,
            value,
            static_cast<int>(length),
            &result[0],
            size,
            nullptr,
            nullptr
        );
    }
    return result;
}

std::vector<CameraDeviceInfo> enumerate_media_foundation() {
    HRESULT initialized = CoInitializeEx(nullptr, COINIT_MULTITHREADED);
    if (FAILED(initialized) && initialized != RPC_E_CHANGED_MODE) {
        return {};
    }
    ScopeGuard com_guard;
    if (SUCCEEDED(initialized)) {
        com_guard.add(&CoUninitialize);
    }
    if (FAILED(MFStartup(MF_VERSION))) {
        return {};
    }
    ScopeGuard mf_guard;
    mf_guard.add([] { MFShutdown(); });

    IMFAttributes* attributes = nullptr;
    if (FAILED(MFCreateAttributes(&attributes, 1))) {
        return {};
    }
    ScopeGuard attributes_guard;
    attributes_guard.add_release(attributes);
    if (FAILED(attributes->SetGUID(
            MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE,
            MF_DEVSOURCE_ATTRIBUTE_SOURCE_TYPE_VIDCAP_GUID
        ))) {
        return {};
    }
    IMFActivate** activates = nullptr;
    UINT32 count = 0;
    if (FAILED(MFEnumDeviceSources(attributes, &activates, &count))) {
        return {};
    }
    ScopeGuard activates_guard;
    activates_guard.add([&] {
        for (UINT32 index = 0; index < count; ++index) {
            activates[index]->Release();
        }
        CoTaskMemFree(activates);
    });

    std::vector<CameraDeviceInfo> devices;
    for (UINT32 index = 0; index < count; ++index) {
        auto modes = media_foundation_modes(activates[index]);
        devices.push_back(CameraDeviceInfo{
            CameraBackend::media_foundation,
            static_cast<int>(devices.size()),
            activate_name(activates[index]),
            std::move(modes),
        });
    }
    return devices;
}
#endif

}  // namespace

std::vector<CameraDeviceInfo> list_camera_devices(CameraBackend backend) {
#ifdef _WIN32
    if (backend == CameraBackend::direct_show) {
        return enumerate_direct_show();
    }
    return enumerate_media_foundation();
#else
    (void)backend;
    return {};
#endif
}

std::vector<CameraDeviceInfo> list_camera_devices() {
    auto devices = list_camera_devices(CameraBackend::direct_show);
    auto media_foundation = list_camera_devices(CameraBackend::media_foundation);
    devices.insert(
        devices.end(),
        std::make_move_iterator(media_foundation.begin()),
        std::make_move_iterator(media_foundation.end())
    );
    return devices;
}

std::optional<CameraDeviceInfo> resolve_camera_device(
    const CameraDeviceConfiguration& configured,
    const std::vector<CameraDeviceInfo>& devices
) {
    std::vector<CameraDeviceInfo> matches;
    for (const auto& device : devices) {
        if (device.backend == configured.backend && device.name == configured.name) {
            matches.push_back(device);
        }
    }
    if (matches.size() == 1) {
        return matches.front();
    }
    for (const auto& device : matches) {
        if (device.index == configured.index) {
            return device;
        }
    }
    return std::nullopt;
}

std::optional<CameraModeInfo> try_resolve_camera_mode(
    const CameraModeConfiguration& configured,
    const std::vector<CameraModeInfo>& modes
) {
    for (const auto& mode : modes) {
        if (mode.width == configured.width && mode.height == configured.height &&
            mode.subtype_guid == configured.subtype_guid &&
            std::abs(mode.fps - configured.fps) <=
                std::max(1e-6, std::abs(configured.fps) * 1e-6)) {
            return mode;
        }
    }
    return std::nullopt;
}

CameraModeInfo resolve_camera_mode(
    const CameraModeConfiguration& configured,
    const std::vector<CameraModeInfo>& modes
) {
    if (const auto mode = try_resolve_camera_mode(configured, modes); mode.has_value()) {
        return *mode;
    }
    throw ConfigurationError(
        "configured camera mode is unavailable: " +
        std::to_string(configured.width) + "x" + std::to_string(configured.height) + "@" +
        std::to_string(configured.fps) + " " + configured.subtype_guid
    );
}

}  // namespace divergencesplitter
