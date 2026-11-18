#include "divergencesplitter/text.hpp"

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <Windows.h>
#endif

namespace divergencesplitter {

std::string path_to_utf8(const std::filesystem::path& path) {
    const auto value = path.u8string();
    return {reinterpret_cast<const char*>(value.data()), value.size()};
}

std::filesystem::path path_from_utf8(std::string_view value) {
    std::u8string text;
    text.assign(reinterpret_cast<const char8_t*>(value.data()), value.size());
    return std::filesystem::path{text};
}

std::string to_utf8(std::wstring_view value) {
    if (value.empty()) {
        return {};
    }
#ifdef _WIN32
    const int size = WideCharToMultiByte(
        CP_UTF8,
        0,
        value.data(),
        static_cast<int>(value.size()),
        nullptr,
        0,
        nullptr,
        nullptr
    );
    if (size <= 0) {
        return {};
    }
    std::string result(static_cast<std::size_t>(size), '\0');
    WideCharToMultiByte(
        CP_UTF8,
        0,
        value.data(),
        static_cast<int>(value.size()),
        result.data(),
        size,
        nullptr,
        nullptr
    );
    return result;
#else
    return std::string{value.begin(), value.end()};
#endif
}

std::wstring to_wide(std::string_view value) {
    if (value.empty()) {
        return {};
    }
#ifdef _WIN32
    const int size = MultiByteToWideChar(
        CP_UTF8,
        0,
        value.data(),
        static_cast<int>(value.size()),
        nullptr,
        0
    );
    if (size <= 0) {
        return {};
    }
    std::wstring result(static_cast<std::size_t>(size), L'\0');
    MultiByteToWideChar(
        CP_UTF8,
        0,
        value.data(),
        static_cast<int>(value.size()),
        result.data(),
        size
    );
    return result;
#else
    return std::wstring{value.begin(), value.end()};
#endif
}

}  // namespace divergencesplitter
