#pragma once

#include <filesystem>
#include <string>
#include <string_view>

namespace divergencesplitter {

// Configuration files store paths as UTF-8 regardless of the active code page.
[[nodiscard]] std::string path_to_utf8(const std::filesystem::path& path);
[[nodiscard]] std::filesystem::path path_from_utf8(std::string_view value);

[[nodiscard]] std::string to_utf8(std::wstring_view value);
[[nodiscard]] std::wstring to_wide(std::string_view value);

}  // namespace divergencesplitter
