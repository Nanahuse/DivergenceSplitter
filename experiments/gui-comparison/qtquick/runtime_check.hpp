#pragma once
#include <QDir>
#include <QFileInfo>
#include <QLibraryInfo>
#include <QQmlEngine>
#include <Windows.h>
#include <Psapi.h>
#include <stdexcept>
#include <iterator>
#include <vector>

// Used only for installed/extracted verification. CTest may use development imports.
inline bool verify_quick_distribution(const QQmlEngine& engine) {
    const auto requested = qEnvironmentVariable("GUI_DISTRIBUTION_ROOT");
    if (requested.isEmpty()) return false;
    const auto root = QFileInfo(requested).canonicalFilePath();
    if (root.isEmpty()) throw std::runtime_error("Distribution verification root missing");
    const auto inside = [&](const QString& path) {
        const auto canonical = QFileInfo(path).canonicalFilePath();
        return canonical.compare(root, Qt::CaseInsensitive) == 0 ||
            canonical.startsWith(root + '/', Qt::CaseInsensitive);
    };
    if (!inside(QLibraryInfo::path(QLibraryInfo::QmlImportsPath)))
        throw std::runtime_error("Qt Quick QML imports escape the distribution");
    for (const auto& path : engine.importPathList())
        if (!path.startsWith("qrc:") && !inside(path))
            throw std::runtime_error("Qt Quick engine has an external import path");
    std::vector<HMODULE> modules(1024);
    DWORD bytes = 0;
    if (!EnumProcessModules(GetCurrentProcess(), modules.data(), DWORD(modules.size() * sizeof(HMODULE)), &bytes) || bytes > modules.size() * sizeof(HMODULE))
        throw std::runtime_error("Cannot enumerate Qt Quick runtime modules");
    for (std::size_t i = 0; i < bytes / sizeof(HMODULE); ++i) {
        wchar_t buffer[32768];
        const auto length = GetModuleFileNameW(modules[i], buffer, DWORD(std::size(buffer)));
        if (!length || length == std::size(buffer)) throw std::runtime_error("Cannot read runtime module path");
        const auto path = QString::fromWCharArray(buffer, int(length));
        const auto name = QFileInfo(path).fileName();
        if ((name.startsWith("Qt6", Qt::CaseInsensitive) || name.endsWith("plugin.dll", Qt::CaseInsensitive) || name.compare("qwindows.dll", Qt::CaseInsensitive) == 0) && !inside(path))
            throw std::runtime_error("Qt Quick runtime module loaded outside the distribution");
    }
    return true;
}
