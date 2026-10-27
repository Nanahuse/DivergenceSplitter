#include "app.hpp"
#include "dialog_test.hpp"
#include "protocol.hpp"
#include <windows.h>
#include <objbase.h>
#include <objidl.h>
#include <WebView2.h>
#include <wrl.h>
#include <shlobj.h>
#include <wincrypt.h>
#include <commdlg.h>
#include <opencv2/imgcodecs.hpp>
#include <opencv2/imgproc.hpp>
#include <algorithm>
#include <fstream>
#include <iostream>
#include <map>
#include <deque>
#include <set>
#include <stdexcept>

using namespace comparison;
using namespace comparison::web;
using Microsoft::WRL::ComPtr;
using Microsoft::WRL::Callback;
namespace {
constexpr wchar_t origin[] = L"https://comparison.local";
constexpr wchar_t document[] = L"https://comparison.local/index.html";
constexpr UINT recover_message = WM_APP + 1, dialog_message = WM_APP + 2;
void check(HRESULT result) { if (FAILED(result)) throw std::runtime_error("WebView2 HRESULT " + std::to_string(unsigned(result))); }
std::wstring wide(const std::string& s) {
    if (s.empty()) return {};
    const auto size = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), int(s.size()), nullptr, 0);
    if (!size) throw std::runtime_error("Invalid UTF-8");
    std::wstring result(size, 0); MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s.data(), int(s.size()), result.data(), size); return result;
}
std::string utf8(const wchar_t* s) {
    const auto size = WideCharToMultiByte(CP_UTF8, 0, s, -1, nullptr, 0, nullptr, nullptr);
    std::string result(size, 0); WideCharToMultiByte(CP_UTF8, 0, s, -1, result.data(), size, nullptr, nullptr); result.pop_back(); return result;
}
std::string jpeg(const Image& image) {
    cv::Mat rgba(int(image.height), int(image.width), CV_8UC4, const_cast<std::uint8_t*>(image.rgba.data()));
    cv::Mat bgr; cv::cvtColor(rgba, bgr, cv::COLOR_RGBA2BGR);
    std::vector<unsigned char> encoded;
    if (!cv::imencode(".jpg", bgr, encoded, {cv::IMWRITE_JPEG_QUALITY, 80})) throw std::runtime_error("JPEG encode failed");
    DWORD size{}; const auto flags = CRYPT_STRING_BASE64 | CRYPT_STRING_NOCRLF;
    if (!CryptBinaryToStringA(encoded.data(), DWORD(encoded.size()), flags, nullptr, &size)) throw std::runtime_error("Base64 size failed");
    std::string result(size, 0);
    if (!CryptBinaryToStringA(encoded.data(), DWORD(encoded.size()), flags, result.data(), &size)) throw std::runtime_error("Base64 failed");
    result.resize(size); if (!result.empty() && result.back() == 0) result.pop_back();
    return "data:image/jpeg;base64," + result;
}
class Host final : public Driver {
public:
    explicit Host(Session& session) : session_(session), script_(session) {
        wchar_t path[32768]{}; GetModuleFileNameW(nullptr, path, 32768);
        assets_ = std::filesystem::path(path).parent_path() / "ui";
        if (!std::filesystem::exists(assets_ / "index.html")) throw std::runtime_error("Missing static UI assets next to executable");
        PWSTR local{}; check(SHGetKnownFolderPath(FOLDERID_LocalAppData, 0, nullptr, &local));
        user_data_ = std::filesystem::path(local) / L"DivergenceSplitter" / L"gui-comparison-webview2" / std::to_wstring(GetCurrentProcessId());
        CoTaskMemFree(local);
        WNDCLASSW wc{}; wc.lpfnWndProc = window_proc; wc.hInstance = GetModuleHandleW(nullptr); wc.lpszClassName = L"DivergenceSplitterWebViewComparison";
        wc.hCursor = LoadCursorW(nullptr, IDC_ARROW); RegisterClassW(&wc);
        window_ = CreateWindowW(wc.lpszClassName, L"DivergenceSplitter comparison - WebView2", WS_OVERLAPPEDWINDOW,
            CW_USEDEFAULT, CW_USEDEFAULT, 1100, 760, nullptr, nullptr, wc.hInstance, this);
        if (!window_) throw std::runtime_error("CreateWindow failed");
        LPWSTR version{};
        const auto available = GetAvailableCoreWebView2BrowserVersionString(nullptr, &version);
        if (FAILED(available) || !version) {
            MessageBoxW(window_, L"Microsoft Edge WebView2 Evergreen Runtime is required.\nInstall it from https://developer.microsoft.com/microsoft-edge/webview2/", L"Missing WebView2 Runtime", MB_OK | MB_ICONERROR);
            throw std::runtime_error("Evergreen Runtime unavailable; no automatic download performed");
        }
        runtime_ = utf8(version); CoTaskMemFree(version);
        session_.renderer = "Win32 / WebView2 " + runtime_ + " / React / JPEG JSON";
        ShowWindow(window_, SW_SHOW); SetTimer(window_, 1, 67, nullptr);
        create_environment();
    }
    ~Host() override { shutdown(); }
    int run() {
        MSG message{};
        while (GetMessageW(&message, nullptr, 0, 0) > 0) { TranslateMessage(&message); DispatchMessageW(&message); }
        shutdown(); session_.engine.stop(); session_.write_report(); write_web_report();
        return session_.error.empty() ? 0 : 1;
    }
    Probe probe() const override {
        auto result = probe_; result.busy = result.busy || dialog_.has_value();
        result.file_cancels = file_cancels_; result.discard_cancels = discard_cancels_; return result;
    }
    void perform(Action action) override {
        if (test_actions_.size() >= 32) throw std::runtime_error("Test action queue full");
        test_actions_.push_back(action);
    }
private:
    template<class F> HRESULT guard(F callback) {
        try { if (!closing_) callback(); }
        catch (const std::exception& e) { fail(e.what()); }
        return S_OK;
    }
    void fail(std::string error) { session_.error = std::move(error); if (window_) PostMessageW(window_, WM_CLOSE, 1, 0); }
    static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
        auto self = reinterpret_cast<Host*>(GetWindowLongPtrW(window, GWLP_USERDATA));
        if (message == WM_NCCREATE) {
            self = static_cast<Host*>(reinterpret_cast<CREATESTRUCTW*>(lparam)->lpCreateParams);
            SetWindowLongPtrW(window, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        }
        if (!self) return DefWindowProcW(window, message, wparam, lparam);
        try {
            switch (message) {
            case WM_TIMER: self->tick(); return 0;
            case WM_SIZE: self->resize(); return 0;
            case WM_KILLFOCUS: self->hold_.cancel(); break;
            case WM_ACTIVATE: if (LOWORD(wparam) == WA_INACTIVE) self->hold_.cancel(); break;
            case recover_message: self->recover(); return 0;
            case dialog_message: self->show_dialog(); return 0;
            case WM_CLOSE:
                if (!wparam && self->session_.profile.dirty() && !self->confirm_discard(false)) return 0;
                self->shutdown(); DestroyWindow(window); return 0;
            case WM_DESTROY: PostQuitMessage(0); return 0;
            }
        } catch (const std::exception& e) { self->fail(e.what()); return 0; }
        return DefWindowProcW(window, message, wparam, lparam);
    }
    void create_environment() {
        std::filesystem::create_directories(user_data_);
        check(CreateCoreWebView2EnvironmentWithOptions(nullptr, user_data_.c_str(), nullptr,
            Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>([this](HRESULT hr, ICoreWebView2Environment* environment) {
                return guard([&] {
                    check(hr); environment_ = environment; check(environment_.As(&environment5_));
                    check(environment5_->add_BrowserProcessExited(Callback<ICoreWebView2BrowserProcessExitedEventHandler>(
                        [this](ICoreWebView2Environment*, ICoreWebView2BrowserProcessExitedEventArgs* args) {
                            return guard([&] {
                                COREWEBVIEW2_BROWSER_PROCESS_EXIT_KIND kind{}; check(args->get_BrowserProcessExitKind(&kind));
                                if (kind == COREWEBVIEW2_BROWSER_PROCESS_EXIT_KIND_FAILED) { ++browser_failures_; recreate_ = true; schedule_recovery(); }
                            });
                        }).Get(), &browser_token_));
                    create_controller();
                });
            }).Get()));
    }
    void create_controller() {
        const auto generation = ++generation_;
        check(environment_->CreateCoreWebView2Controller(window_, Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
            [this, generation](HRESULT hr, ICoreWebView2Controller* controller) {
                return guard([&] {
                    if (generation != generation_) return;
                    check(hr); controller_ = controller; check(controller_->get_CoreWebView2(&web_));
                    configure(); resize(); check(controller_->put_IsVisible(TRUE)); check(web_->Navigate(document));
                });
            }).Get()));
    }
    void configure() {
        ComPtr<ICoreWebView2_3> web3; check(web_.As(&web3));
        check(web3->SetVirtualHostNameToFolderMapping(L"comparison.local", assets_.c_str(), COREWEBVIEW2_HOST_RESOURCE_ACCESS_KIND_DENY_CORS));
        ComPtr<ICoreWebView2Settings> settings; check(web_->get_Settings(&settings));
        check(settings->put_AreHostObjectsAllowed(FALSE)); check(settings->put_AreDefaultScriptDialogsEnabled(FALSE));
        check(settings->put_AreDevToolsEnabled(session_.options.self_test ? TRUE : FALSE));
        check(settings->put_AreDefaultContextMenusEnabled(FALSE));
        check(web_->add_NavigationStarting(Callback<ICoreWebView2NavigationStartingEventHandler>([this](ICoreWebView2*, ICoreWebView2NavigationStartingEventArgs* args) {
            return guard([&] {
                LPWSTR uri{}; check(args->get_Uri(&uri)); const bool allowed = std::wstring_view(uri) == document; CoTaskMemFree(uri);
                check(args->put_Cancel(!allowed));
                if (allowed) { ++epoch_; ready_ = false; waiting_since_ = std::chrono::steady_clock::now(); inflight_ = false; sent_topology_.reset(); held_frame_.reset(); reference_cache_.clear(); hold_.cancel(); reference_ids_.clear(); }
            });
        }).Get(), &navigation_token_));
        check(web_->add_NewWindowRequested(Callback<ICoreWebView2NewWindowRequestedEventHandler>([](ICoreWebView2*, ICoreWebView2NewWindowRequestedEventArgs* args) { return args->put_Handled(TRUE); }).Get(), &new_window_token_));
        check(web_->add_PermissionRequested(Callback<ICoreWebView2PermissionRequestedEventHandler>([](ICoreWebView2*, ICoreWebView2PermissionRequestedEventArgs* args) { return args->put_State(COREWEBVIEW2_PERMISSION_STATE_DENY); }).Get(), &permission_token_));
        check(web_->add_WebMessageReceived(Callback<ICoreWebView2WebMessageReceivedEventHandler>([this](ICoreWebView2*, ICoreWebView2WebMessageReceivedEventArgs* args) {
            return guard([&] {
                LPWSTR source{}; check(args->get_Source(&source)); const bool allowed = std::wstring_view(source) == document; CoTaskMemFree(source);
                if (!allowed) { ++rejected_origins_; return; }
                LPWSTR raw{}; check(args->get_WebMessageAsJson(&raw));
                const auto text = utf8(raw); CoTaskMemFree(raw);
                if (text.size() > 262144) { ++rejected_messages_; return; }
                Json request;
                try { request = Json::parse(text); validate_envelope(request, epoch_); command(request); }
                catch (const std::exception& e) { ++rejected_messages_; if (request.is_object() && request.contains("id") && request["id"].is_number_unsigned()) respond(request["id"], false, {}, e.what()); }
            });
        }).Get(), &message_token_));
        check(web_->add_ProcessFailed(Callback<ICoreWebView2ProcessFailedEventHandler>([this](ICoreWebView2*, ICoreWebView2ProcessFailedEventArgs* args) {
            return guard([&] {
                COREWEBVIEW2_PROCESS_FAILED_KIND kind{}; check(args->get_ProcessFailedKind(&kind));
                if (kind == COREWEBVIEW2_PROCESS_FAILED_KIND_BROWSER_PROCESS_EXITED) {
                    // BrowserProcessExited owns recreation after all child processes have exited.
                    ready_ = false; inflight_ = false; hold_.cancel();
                } else if (kind == COREWEBVIEW2_PROCESS_FAILED_KIND_RENDER_PROCESS_EXITED || kind == COREWEBVIEW2_PROCESS_FAILED_KIND_RENDER_PROCESS_UNRESPONSIVE) {
                    ++renderer_failures_; schedule_recovery();
                }
            });
        }).Get(), &failed_token_));
    }
    void resize() { if (controller_) { RECT bounds{}; GetClientRect(window_, &bounds); check(controller_->put_Bounds(bounds)); } }
    void post(const Json& value) { if (web_) check(web_->PostWebMessageAsJson(wide(value.dump()).c_str())); }
    void respond(std::uint64_t id, bool ok, Json result = {}, std::string error = {}) {
        post({{"version", 1}, {"type", "response"}, {"epoch", epoch_}, {"id", id}, {"ok", ok}, {"result", result}, {"error", error}});
    }
    void command(const Json& request) {
        const auto name = request.at("command").get<std::string>(); const auto& args = request.at("args");
        const auto id = request.at("id").get<std::uint64_t>(); Json result = Json::object();
        if (name == "ready") { if (ready_) throw std::invalid_argument("Already ready"); ready_ = true; respond(id, true, profile_json(session_.profile.draft)); return; }
        if (!ready_) throw std::invalid_argument("Document not ready");
        if (name == "ack") {
            if (!inflight_ || args.at("delivery") != delivery_) return;
            inflight_ = false; const auto& p = args.at("probe");
            const auto page = p.at("page").get<std::string>();
            probe_.page = page == "diagnostics" ? Page::diagnostics : page == "profile" ? Page::profile : Page::monitor;
            probe_.expanded = p.at("expanded").get<bool>(); probe_.dirty = p.at("dirty").get<bool>(); probe_.errors = p.at("errors").get<bool>();
            probe_.references = p.at("references").get<std::size_t>(); probe_.draft_count = p.at("draft_count").get<std::size_t>();
            probe_.scroll = p.at("scroll").get<int>(); probe_.busy = p.at("busy").get<bool>();
            session_.counters.topology_builds = p.at("tree_builds").get<std::uint64_t>();
            session_.counters.value_updates = p.at("value_updates").get<std::uint64_t>();
            max_dom_rows_ = std::max(max_dom_rows_, p.at("rendered_rows").get<unsigned>());
            reference_ids_.clear();
            if (probe_.page == Page::diagnostics) {
                if (p.at("reference_ids").size() > 16) throw std::invalid_argument("Reference limit exceeded");
                for (const auto& value : p.at("reference_ids")) reference_ids_.insert(std::stoull(value.get<std::string>()));
            }
            if (held_frame_) { session_.observe_frame(*held_frame_); held_frame_.reset(); ++decoded_frames_; }
            return;
        }
        if (name == "page") { const auto page = args.at("page").get<std::string>(); if (page != "monitor" && page != "diagnostics" && page != "profile") throw std::invalid_argument("Unknown page"); hold_.cancel(); if (page != "diagnostics") { reference_ids_.clear(); reference_cache_.clear(); } }
        else if (name == "running") { hold_.cancel(); session_.engine.set_running(args.at("value").get<bool>()); }
        else if (name == "mutate") { if (!session_.engine.mutate_topology()) throw std::runtime_error("Topology input busy"); }
        else if (name == "draft") { session_.profile.draft = parse_profile(args.at("profile")); }
        else if (name == "apply") {
            const auto candidate = parse_profile(args.at("profile")); const auto errors = validate(candidate);
            session_.profile.draft = candidate;
            if (errors.empty()) { const auto backend_errors = session_.engine.apply_profile(candidate); if (!backend_errors.empty()) { respond(id, true, {{"errors", backend_errors}}); return; } (void)session_.profile.apply(); }
            result = {{"errors", errors}};
        }
        else if (name == "add") { session_.profile.add_scenario(); result = profile_json(session_.profile.draft); }
        else if (name == "remove") { session_.profile.remove_scenario(std::stoull(args.at("id").get<std::string>())); result = profile_json(session_.profile.draft); }
        else if (name == "discard") { session_.profile.discard(); result = profile_json(session_.profile.draft); }
        else if (name == "browse" || name == "fresh") {
            if (dialog_) throw std::runtime_error("Dialog busy"); dialog_ = std::make_pair(id, name); PostMessageW(window_, dialog_message, 0, 0); return;
        }
        else if (name == "holdPress") { hold_.press(std::chrono::steady_clock::now()); }
        else if (name == "holdCancel") { hold_.cancel(); }
        else if (name == "resize") { SetWindowPos(window_, nullptr, 0, 0, 800, 600, SWP_NOMOVE | SWP_NOZORDER); }
        else if (name == "reload") { respond(id, true); check(web_->Reload()); return; }
        else if (name == "uiError") { fail(args.at("error").get<std::string>()); return; }
        else throw std::invalid_argument("Unknown command");
        respond(id, true, result);
    }
    bool confirm_discard(bool test) {
        hold_.cancel(); CancelNativeDialog cancel(test);
        const auto answer = MessageBoxW(window_, L"Discard unapplied changes?", L"Unsaved Configuration", MB_OKCANCEL | MB_DEFBUTTON2);
        if (answer != IDOK) ++discard_cancels_;
        return answer == IDOK;
    }
    void show_dialog() {
        if (!dialog_) return;
        const auto [id, name] = *dialog_; Json result;
        if (name == "fresh") { if (!session_.profile.dirty() || confirm_discard(session_.options.self_test)) session_.profile.draft = Profile{}; }
        else {
            hold_.cancel(); CancelNativeDialog cancel(session_.options.self_test);
            wchar_t file[32768]{}; OPENFILENAMEW options{}; options.lStructSize = sizeof(options); options.hwndOwner = window_;
            options.lpstrFile = file; options.nMaxFile = 32768; options.lpstrFilter = L"Video files\0*.avi;*.mp4\0All files\0*.*\0";
            options.Flags = OFN_FILEMUSTEXIST | OFN_NOCHANGEDIR | OFN_EXPLORER;
            if (GetOpenFileNameW(&options)) { session_.profile.draft.file = utf8(file); session_.profile.draft.source = Source::synthetic_file; }
            else if (CommDlgExtendedError()) throw std::runtime_error("Native file dialog failed"); else ++file_cancels_;
        }
        dialog_.reset(); respond(id, true, profile_json(session_.profile.draft));
    }
    void publish() {
        if (!ready_ || inflight_ || dialog_) return;
        const auto state = session_.engine.state();
        Json metrics = Json::array();
        for (const auto& m : state->metrics) metrics.push_back(Json::array({std::to_string(m.id), m.score, m.active, m.connected, m.enabled}));
        Json value = {{"version", 1}, {"type", "snapshot"}, {"epoch", epoch_}, {"delivery", ++delivery_},
            {"sequence", std::to_string(state->sequence)}, {"revision", std::to_string(state->topology->revision)}, {"running", state->running},
            {"resets", std::to_string(state->resets)}, {"metrics", metrics}, {"profile", profile_json(*state->applied_profile)}};
        if (sent_topology_ != state->topology && (probe_.page == Page::diagnostics || !sent_topology_)) { value["nodes"] = topology_json(*state->topology); sent_topology_ = state->topology; }
        std::set<NodeId> live;
        for (const auto& node : state->topology->nodes) if (node.kind == NodeKind::detector) live.insert(node.id);
        std::erase_if(reference_cache_, [&](const auto& pair) { return !reference_ids_.contains(pair.first) || !live.contains(pair.first); });
        Json references = Json::object();
        for (auto id : reference_ids_) if (live.contains(id)) {
            if (!reference_cache_.contains(id)) reference_cache_[id] = jpeg(reference_image(session_.engine, id, state->topology));
            references[std::to_string(id)] = reference_cache_.at(id);
        }
        value["references"] = references;
        if (probe_.page == Page::monitor) {
            auto frame = session_.engine.frame();
            if (frame && frame->sequence > session_.counters.last_frame) { held_frame_ = frame; value["frame"] = {{"sequence", std::to_string(frame->sequence)}, {"jpeg", jpeg(frame->image)}}; }
        }
        inflight_ = true; sent_at_ = std::chrono::steady_clock::now(); ++sent_snapshots_; post(value);
    }
    void schedule_recovery() {
        ready_ = false; inflight_ = false; hold_.cancel();
        if (!recovery_pending_) { recovery_pending_ = true; PostMessageW(window_, recover_message, 0, 0); }
    }
    void recover() {
        if (!recovery_pending_ || closing_) return;
        recovery_pending_ = false;
        if (++recoveries_ > 3) { fail("WebView2 recovery limit reached"); return; }
        if (recreate_) { recreate_ = false; close_controller(); create_controller(); }
        else if (web_) check(web_->Reload());
    }
    void tick() {
        if (closing_ || dialog_ || finishing_) return;
        if (hold_.poll(std::chrono::steady_clock::now())) session_.engine.reset_all();
        session_.sample_process();
        if (inflight_ && std::chrono::steady_clock::now() - sent_at_ > std::chrono::seconds(10)) schedule_recovery();
        if (!ready_ && std::chrono::steady_clock::now() - waiting_since_ > std::chrono::seconds(20) && !recovery_pending_) { fail("WebView2 ready timeout"); return; }
        if (ready_) {
            if (session_.options.self_test) {
                if (!contract_done_) contract_done_ = script_.tick(*this);
                else if (test_actions_.empty()) recovery_test();
            } else session_.exercise(*this);
            if (!test_actions_.empty() && !inflight_ && !probe_.busy) {
                post({{"testAction", int(test_actions_.front())}}); test_actions_.pop_front();
            }
            publish();
        }
        if (session_.expired()) finish();
    }
    void recovery_test() {
        if (!session_.error.empty() || inflight_) return;
        const auto state = session_.engine.state();
        if (recovery_step_ == 0) {
            if (max_dom_rows_ > 100) { fail("Diagnostics DOM was not bounded"); return; }
            session_.checks.push_back("W01_virtualized_rows_bounded");
            old_epoch_ = epoch_; sequence_before_reload_ = state->sequence; old_resets_ = state->resets;
            ++recovery_step_; check(web_->Reload());
        } else if (recovery_step_ == 1 && epoch_ > old_epoch_) {
            if (state->sequence <= sequence_before_reload_ || state->resets != old_resets_) { fail("Reload lost Core state"); return; }
            session_.checks.push_back("W02_reload_keeps_core"); old_epoch_ = epoch_; ++recovery_step_;
            check(web_->CallDevToolsProtocolMethod(L"Page.crash", L"{}", Callback<ICoreWebView2CallDevToolsProtocolMethodCompletedHandler>([](HRESULT, LPCWSTR) { return S_OK; }).Get()));
        } else if (recovery_step_ == 2 && epoch_ > old_epoch_ && renderer_failures_) {
            session_.checks.push_back("W03_renderer_failure_reload"); old_epoch_ = epoch_; ++recovery_step_;
            UINT32 pid{}; check(web_->get_BrowserProcessId(&pid));
            HANDLE process = OpenProcess(PROCESS_TERMINATE, FALSE, pid);
            if (!process) throw std::runtime_error("Cannot open this host's browser process");
            const auto killed = TerminateProcess(process, 1); CloseHandle(process);
            if (!killed) throw std::runtime_error("Browser failure injection failed");
        } else if (recovery_step_ == 3 && epoch_ > old_epoch_ && browser_failures_) {
            if (state->resets != old_resets_) { fail("Recovery lost Core resets"); return; }
            session_.checks.push_back("W04_browser_failure_recreation"); finish();
        }
    }
    void finish() {
        if (finishing_) return; finishing_ = true; hold_.cancel();
        if (!session_.options.capture.empty() && web_) {
            ComPtr<IStream> stream; check(CreateStreamOnHGlobal(nullptr, TRUE, &stream));
            check(web_->CapturePreview(COREWEBVIEW2_CAPTURE_PREVIEW_IMAGE_FORMAT_PNG, stream.Get(),
                Callback<ICoreWebView2CapturePreviewCompletedHandler>([this, stream](HRESULT hr) {
                    return guard([&] {
                        check(hr); HGLOBAL memory{}; check(GetHGlobalFromStream(stream.Get(), &memory));
                        STATSTG stat{}; check(stream->Stat(&stat, STATFLAG_NONAME));
                        const auto data = GlobalLock(memory); std::ofstream out(session_.options.capture, std::ios::binary);
                        out.write(static_cast<const char*>(data), std::streamsize(stat.cbSize.QuadPart)); GlobalUnlock(memory);
                        PostMessageW(window_, WM_CLOSE, 1, 0);
                    });
                }).Get()));
        } else PostMessageW(window_, WM_CLOSE, 1, 0);
    }
    void close_controller() {
        if (web_) {
            web_->remove_NavigationStarting(navigation_token_); web_->remove_WebMessageReceived(message_token_);
            web_->remove_ProcessFailed(failed_token_); web_->remove_NewWindowRequested(new_window_token_); web_->remove_PermissionRequested(permission_token_);
        }
        if (controller_) controller_->Close();
        web_.Reset(); controller_.Reset(); ready_ = false; inflight_ = false; held_frame_.reset(); reference_cache_.clear();
    }
    void shutdown() {
        if (closing_) return; closing_ = true; hold_.cancel(); if (window_) KillTimer(window_, 1);
        close_controller();
        if (environment5_) environment5_->remove_BrowserProcessExited(browser_token_);
        environment5_.Reset(); environment_.Reset();
        // Runtime owns the cache until all its processes exit. Never remove a live UDF.
        // The per-process directory is retained for inspection; it is outside the ZIP.
    }
    void write_web_report() {
        if (session_.options.report.empty()) return;
        auto path = session_.options.report; path.replace_extension("webview2.json");
        std::ofstream out(path);
        out << Json({{"runtime", runtime_}, {"user_data_folder", utf8(user_data_.c_str())}, {"static_assets", utf8(assets_.c_str())},
            {"transport", "JPEG base64 JSON; maximum one unacknowledged snapshot/frame"}, {"sent_snapshots", sent_snapshots_},
            {"decoded_frame_acks", decoded_frames_}, {"max_dom_rows", max_dom_rows_}, {"recoveries", recoveries_},
            {"renderer_failures", renderer_failures_}, {"browser_failures", browser_failures_}, {"rejected_messages", rejected_messages_},
            {"rejected_origins", rejected_origins_}, {"cpu_memory_scope", "Session report is host-only; use process-tree sampling for comparison"},
            {"not_verified", {"physical IME", "GPU memory", "display scanout", "controlled performance ranking"}}}).dump(2);
    }
    Session& session_; ContractScript script_; HWND window_{};
    ComPtr<ICoreWebView2Environment> environment_; ComPtr<ICoreWebView2Environment5> environment5_;
    ComPtr<ICoreWebView2Controller> controller_; ComPtr<ICoreWebView2> web_;
    EventRegistrationToken navigation_token_{}, message_token_{}, failed_token_{}, new_window_token_{}, permission_token_{}, browser_token_{};
    std::filesystem::path assets_, user_data_; std::string runtime_;
    Probe probe_; ResetHold hold_; std::optional<std::pair<std::uint64_t, std::string>> dialog_;
    std::deque<Action> test_actions_;
    std::shared_ptr<const Topology> sent_topology_; std::shared_ptr<const Frame> held_frame_;
    std::set<NodeId> reference_ids_; std::map<NodeId, std::string> reference_cache_;
    Time sent_at_{}, waiting_since_ = std::chrono::steady_clock::now();
    bool ready_ = false, inflight_ = false, closing_ = false, finishing_ = false, recreate_ = false, recovery_pending_ = false, contract_done_ = false;
    unsigned epoch_ = 0, generation_ = 0, recoveries_ = 0, max_dom_rows_ = 0, file_cancels_ = 0, discard_cancels_ = 0;
    unsigned renderer_failures_ = 0, browser_failures_ = 0, rejected_messages_ = 0, rejected_origins_ = 0, recovery_step_ = 0, old_epoch_ = 0;
    std::uint64_t delivery_ = 0, decoded_frames_ = 0, sent_snapshots_ = 0, sequence_before_reload_ = 0, old_resets_ = 0;
};
}
int main(int argc, char** argv) {
    try {
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        check(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED));
        int result;
        { Session session(Options::parse(argc, argv), "webview2"); Host host(session); result = host.run(); }
        CoUninitialize(); return result;
    } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
