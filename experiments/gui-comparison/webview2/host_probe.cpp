// Disposable wrapper feasibility probe. The comparison application uses main.cpp.
#include <webview.h>
#include <wrl.h>
#include <iostream>
#include <filesystem>
using Microsoft::WRL::ComPtr;
using Microsoft::WRL::Callback;
int main(int argc, char** argv) {
    if (argc != 2) return 2;
    try {
        webview::webview window(false, nullptr);
        auto controller = static_cast<ICoreWebView2Controller*>(window.browser_controller().value());
        if (!controller) return 3;
        ComPtr<ICoreWebView2> browser; if (FAILED(controller->get_CoreWebView2(&browser))) return 4;
        ComPtr<ICoreWebView2_3> browser3; if (FAILED(browser.As(&browser3))) return 5;
        const auto assets = std::filesystem::absolute(argv[1]);
        if (FAILED(browser3->SetVirtualHostNameToFolderMapping(L"probe.local", assets.c_str(), COREWEBVIEW2_HOST_RESOURCE_ACCESS_KIND_DENY_CORS))) return 6;
        ComPtr<ICoreWebView2_2> browser2; if (FAILED(browser.As(&browser2))) return 7;
        ComPtr<ICoreWebView2Environment> environment; browser2->get_Environment(&environment);
        ComPtr<ICoreWebView2Environment5> environment5; if (FAILED(environment.As(&environment5))) return 8;
        unsigned calls = 0; EventRegistrationToken failed{}, exited{};
        browser->add_ProcessFailed(Callback<ICoreWebView2ProcessFailedEventHandler>([](ICoreWebView2*, ICoreWebView2ProcessFailedEventArgs*) { return S_OK; }).Get(), &failed);
        environment5->add_BrowserProcessExited(Callback<ICoreWebView2BrowserProcessExitedEventHandler>([](ICoreWebView2Environment*, ICoreWebView2BrowserProcessExitedEventArgs*) { return S_OK; }).Get(), &exited);
        window.bind("probe", [&](const std::string& request) {
            if (request != "[\"roundtrip\"]") throw std::runtime_error("Wrapper roundtrip mismatch");
            if (++calls == 1) window.dispatch([&] { browser->Reload(); });
            else window.dispatch([&] { window.terminate(); });
            return "{\"ok\":true}";
        });
        window.set_title("Disposable webview/webview API probe"); window.set_size(500, 300, WEBVIEW_HINT_NONE);
        const auto timeout = SetTimer(nullptr, 0, 10000, [](HWND, UINT, UINT_PTR, DWORD) { PostQuitMessage(1); });
        window.navigate("https://probe.local/index.html"); window.run(); KillTimer(nullptr, timeout);
        browser->remove_ProcessFailed(failed); environment5->remove_BrowserProcessExited(exited);
        if (calls != 2) return 9;
        std::cout << "wrapper 0.12.0: static mapping, bind roundtrip, reload, native controller, ProcessFailed and BrowserProcessExited interfaces passed\n";
    } catch (const std::exception& e) { std::cerr << e.what(); return 1; }
}
