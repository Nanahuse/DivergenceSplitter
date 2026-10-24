#pragma once
#include <windows.h>
namespace comparison {
// In-process test helper: cancel only this application's modal native dialog.
// It is never armed during normal interactive use and never targets another process.
class CancelNativeDialog {
public:
    explicit CancelNativeDialog(bool enabled) {
        if (enabled) timer_ = SetTimer(nullptr, 0, 50, [](HWND, UINT, UINT_PTR, DWORD) {
            EnumThreadWindows(GetCurrentThreadId(), [](HWND window, LPARAM) -> BOOL {
                wchar_t name[64]{};
                GetClassNameW(window, name, 64);
                if (lstrcmpW(name, L"#32770") == 0 && IsWindowVisible(window)) PostMessageW(window, WM_CLOSE, 0, 0);
                return TRUE;
            }, 0);
        });
    }
    ~CancelNativeDialog() { if (timer_) KillTimer(nullptr, timer_); }
private:
    UINT_PTR timer_ = 0;
};
}
