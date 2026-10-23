#include "app.hpp"
#include "dialog_test.hpp"
#include <imgui.h>
#include <imgui_stdlib.h>
#include <imgui_impl_win32.h>
#include <imgui_impl_dx11.h>
#include <d3d11.h>
#include <dxgi.h>
#include <shobjidl.h>
#include <wrl/client.h>
#include <algorithm>
#include <deque>
#include <iostream>
#include <unordered_map>
#include <unordered_set>

extern IMGUI_IMPL_API LRESULT ImGui_ImplWin32_WndProcHandler(HWND, UINT, WPARAM, LPARAM);
using namespace comparison;
using Microsoft::WRL::ComPtr;
namespace {
void checked(HRESULT result, const char* message) { if (FAILED(result)) throw std::runtime_error(message); }
struct Texture {
    ComPtr<ID3D11ShaderResourceView> view;
    float width = 0, height = 0;
};
class Window final : public Driver {
public:
    explicit Window(Session& session) : session_(session), script_(session) {
        WNDCLASSW type{}; type.lpfnWndProc = procedure; type.hInstance = GetModuleHandleW(nullptr);
        type.lpszClassName = L"DivergenceSplitterImGuiComparison"; type.hCursor = LoadCursorW(nullptr, IDC_ARROW);
        if (!RegisterClassW(&type) && GetLastError() != ERROR_CLASS_ALREADY_EXISTS) throw std::runtime_error("RegisterClass failed");
        hwnd_ = CreateWindowW(type.lpszClassName, L"DivergenceSplitter comparison - Dear ImGui", WS_OVERLAPPEDWINDOW,
            CW_USEDEFAULT, CW_USEDEFAULT, 1100, 760, nullptr, nullptr, type.hInstance, this);
        if (!hwnd_) throw std::runtime_error("CreateWindow failed");
        DXGI_SWAP_CHAIN_DESC swap{}; swap.BufferCount = 2; swap.BufferDesc.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        swap.BufferUsage = DXGI_USAGE_RENDER_TARGET_OUTPUT; swap.OutputWindow = hwnd_; swap.SampleDesc.Count = 1;
        swap.Windowed = TRUE; swap.SwapEffect = DXGI_SWAP_EFFECT_DISCARD;
        D3D_FEATURE_LEVEL feature;
        const D3D_FEATURE_LEVEL levels[]{D3D_FEATURE_LEVEL_11_0, D3D_FEATURE_LEVEL_10_0};
        auto result = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0, levels, 2,
            D3D11_SDK_VERSION, &swap, &swapchain_, &device_, &feature, &context_);
        session_.renderer = "Dear ImGui / Win32 / D3D11 hardware";
        if (FAILED(result)) {
            result = D3D11CreateDeviceAndSwapChain(nullptr, D3D_DRIVER_TYPE_WARP, nullptr, 0, levels, 2,
                D3D11_SDK_VERSION, &swap, &swapchain_, &device_, &feature, &context_);
            session_.renderer = "Dear ImGui / Win32 / D3D11 WARP";
        }
        checked(result, "D3D11 device creation failed"); make_target();
        IMGUI_CHECKVERSION(); ImGui::CreateContext();
        auto& io = ImGui::GetIO(); io.IniFilename = nullptr; io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard;
        ImGui::StyleColorsLight(); base_style_ = ImGui::GetStyle();
        dpi_ = float(GetDpiForWindow(hwnd_)) / 96.0f; apply_style();
        if (!ImGui_ImplWin32_Init(hwnd_) || !ImGui_ImplDX11_Init(device_.Get(), context_.Get())) throw std::runtime_error("ImGui backend init failed");
        ShowWindow(hwnd_, SW_SHOW); UpdateWindow(hwnd_);
    }
    ~Window() {
        references_.clear(); preview_ = {};
        ImGui_ImplDX11_Shutdown(); ImGui_ImplWin32_Shutdown(); ImGui::DestroyContext();
        target_.Reset(); swapchain_.Reset(); context_.Reset(); device_.Reset();
        if (IsWindow(hwnd_)) DestroyWindow(hwnd_);
    }
    int run() {
        auto deadline = std::chrono::steady_clock::now();
        while (!quit_) {
            MSG message{};
            while (PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
                if (message.message == WM_QUIT) quit_ = true;
                TranslateMessage(&message); DispatchMessageW(&message);
            }
            if (quit_) break;
            ImGui_ImplDX11_NewFrame(); ImGui_ImplWin32_NewFrame(); inject_input(); ImGui::NewFrame();
            draw(); ImGui::Render();
            const float background[]{.15f, .16f, .18f, 1};
            ID3D11RenderTargetView* target = target_.Get(); context_->OMSetRenderTargets(1, &target, nullptr);
            context_->ClearRenderTargetView(target, background); ImGui_ImplDX11_RenderDrawData(ImGui::GetDrawData());
            if ((session_.options.self_test && script_.tick(*this)) || session_.expired()) {
                capture(); quit_ = true;
            }
            checked(swapchain_->Present(1, 0), "Present failed");
            deadline += std::chrono::nanoseconds(1'000'000'000 / 60);
            auto now = std::chrono::steady_clock::now(); if (deadline < now) deadline = now;
            std::this_thread::sleep_until(deadline);
        }
        references_.clear(); preview_ = {}; session_.engine.stop(); session_.write_report();
        return session_.error.empty() ? 0 : 1;
    }
    Probe probe() const override {
        Probe p; p.page = page_; p.expanded = expanded_.contains(first_detector());
        p.dirty = session_.profile.dirty(); p.errors = !error_.empty(); p.references = references_.size();
        p.draft_count = session_.profile.draft.scenarios.size(); p.scroll = scroll_; p.busy = !input_.empty();
        p.file_cancels = file_cancels_; p.discard_cancels = discard_cancels_; return p;
    }
    void perform(Action action) override {
        switch (action) {
        case Action::monitor: set_page(Page::monitor); break;
        case Action::diagnostics: set_page(Page::diagnostics); break;
        case Action::profile: set_page(Page::profile); break;
        case Action::expand: {
            auto topology = session_.engine.state()->topology;
            std::unordered_map<NodeId, NodeId> parents; for (const auto& node : topology->nodes) parents[node.id] = node.parent;
            for (auto id = first_detector(); id; id = parents.at(id)) open_requests_[id] = true;
            break;
        }
        case Action::collapse: open_requests_[first_detector()] = false; break;
        case Action::mutate: queue_click("Mutate"); break;
        case Action::invalid_draft: input_.push_back({"Name", "", true}); break;
        case Action::valid_draft: input_.push_back({"Name", "Edited scenario", true}); break;
        case Action::apply: queue_click("Apply"); break;
        case Action::add_scenario: queue_click("Add Scenario"); break;
        case Action::remove_scenario: queue_click("Remove Scenario"); break;
        case Action::file_cancel: cancel_file_ = true; queue_click("Browse..."); break;
        case Action::unsaved_cancel: input_.push_back({"Name", "Unsaved", true}); cancel_discard_ = true; queue_click("New Profile"); break;
        case Action::discard: queue_click("Discard"); break;
        case Action::reset_press: input_.push_back({"Reset All", "", false, true}); break;
        case Action::reset_release: ImGui::GetIO().AddMouseButtonEvent(0, false); break;
        case Action::reset_cancel: SendMessageW(hwnd_, WM_KILLFOCUS, 0, 0); break;
        case Action::theme: queue_click("Light / dark"); break;
        case Action::resize: SetWindowPos(hwnd_, nullptr, 0, 0, 800, 600, SWP_NOMOVE | SWP_NOZORDER); break;
        case Action::start: session_.engine.set_running(true); break;
        case Action::stop: hold_.cancel(); session_.engine.set_running(false); break;
        case Action::scroll:
            for (const auto& node : session_.engine.state()->topology->nodes) if (node.kind == NodeKind::scenario) open_requests_[node.id] = true;
            scroll_request_ = true; break;
        }
    }
private:
    struct Input { std::string item, text; bool edit = false, hold = false; int phase = 0; };
    static LRESULT CALLBACK procedure(HWND hwnd, UINT message, WPARAM wparam, LPARAM lparam) {
        auto self = reinterpret_cast<Window*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
        if (message == WM_NCCREATE) {
            self = static_cast<Window*>(reinterpret_cast<CREATESTRUCTW*>(lparam)->lpCreateParams);
            SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(self));
        }
        if (ImGui::GetCurrentContext() && ImGui_ImplWin32_WndProcHandler(hwnd, message, wparam, lparam)) return 1;
        if (self) {
            if (message == WM_KILLFOCUS) self->hold_.cancel();
            if (message == WM_DPICHANGED) {
                self->dpi_ = float(HIWORD(wparam)) / 96.0f;
                if (ImGui::GetCurrentContext()) self->apply_style();
                auto rectangle = reinterpret_cast<RECT*>(lparam);
                SetWindowPos(hwnd, nullptr, rectangle->left, rectangle->top, rectangle->right - rectangle->left,
                    rectangle->bottom - rectangle->top, SWP_NOZORDER); return 0;
            }
            if (message == WM_SIZE && self->device_ && wparam != SIZE_MINIMIZED) {
                self->context_->OMSetRenderTargets(0, nullptr, nullptr);
                self->target_.Reset();
                auto result = self->swapchain_->ResizeBuffers(0, LOWORD(lparam), HIWORD(lparam), DXGI_FORMAT_UNKNOWN, 0);
                if (SUCCEEDED(result)) self->make_target();
                else { self->session_.error = "ResizeBuffers failed"; self->quit_ = true; }
                return 0;
            }
            if (message == WM_CLOSE) {
                self->hold_.cancel();
                if (self->session_.profile.dirty() && !self->confirm_discard()) return 0;
                self->quit_ = true; return 0;
            }
        }
        if (message == WM_DESTROY) { PostQuitMessage(0); return 0; }
        return DefWindowProcW(hwnd, message, wparam, lparam);
    }
    void make_target() {
        ComPtr<ID3D11Texture2D> buffer; checked(swapchain_->GetBuffer(0, IID_PPV_ARGS(&buffer)), "Swapchain buffer failed");
        checked(device_->CreateRenderTargetView(buffer.Get(), nullptr, &target_), "Render target failed");
    }
    Texture texture(const Image& image) {
        D3D11_TEXTURE2D_DESC description{}; description.Width = image.width; description.Height = image.height;
        description.MipLevels = 1; description.ArraySize = 1; description.Format = DXGI_FORMAT_R8G8B8A8_UNORM;
        description.SampleDesc.Count = 1; description.Usage = D3D11_USAGE_DEFAULT; description.BindFlags = D3D11_BIND_SHADER_RESOURCE;
        D3D11_SUBRESOURCE_DATA data{}; data.pSysMem = image.rgba.data(); data.SysMemPitch = image.width * 4;
        ComPtr<ID3D11Texture2D> resource; checked(device_->CreateTexture2D(&description, &data, &resource), "Texture creation failed");
        Texture result; result.width = float(image.width); result.height = float(image.height);
        checked(device_->CreateShaderResourceView(resource.Get(), nullptr, &result.view), "Texture view failed"); return result;
    }
    static void draw_image(const Texture& value, ImVec2 size) {
        ImGui::Image(ImTextureRef(ImTextureID(reinterpret_cast<std::uintptr_t>(value.view.Get()))), size);
    }
    void remember(const std::string& item) { rectangles_[item] = {ImGui::GetItemRectMin().x, ImGui::GetItemRectMin().y, ImGui::GetItemRectMax().x, ImGui::GetItemRectMax().y}; }
    template<class F> void button(const char* label, F callback) {
        const bool clicked = ImGui::Button(label); remember(label); if (clicked) callback();
    }
    void queue_click(const char* item) { input_.push_back({item}); }
    void inject_input() {
        if (input_.empty()) return;
        auto& input = input_.front(); auto found = rectangles_.find(input.item); if (found == rectangles_.end()) return;
        auto& io = ImGui::GetIO(); const auto rectangle = found->second;
        io.AddFocusEvent(true); io.AddMousePosEvent((rectangle.x + rectangle.z) * .5f, (rectangle.y + rectangle.w) * .5f);
        if (input.phase == 0) io.AddMouseButtonEvent(0, true);
        else if (input.phase == 1) {
            if (input.hold) { input_.pop_front(); return; }
            io.AddMouseButtonEvent(0, false);
            if (input.edit) { io.AddKeyEvent(ImGuiMod_Ctrl, true); io.AddKeyEvent(ImGuiKey_A, true); }
            else { input_.pop_front(); return; }
        } else if (input.phase == 2) {
            io.AddKeyEvent(ImGuiKey_A, false); io.AddKeyEvent(ImGuiMod_Ctrl, false); io.AddKeyEvent(ImGuiKey_Backspace, true);
        } else if (input.phase == 3) {
            io.AddKeyEvent(ImGuiKey_Backspace, false); if (!input.text.empty()) io.AddInputCharactersUTF8(input.text.c_str());
        } else { input_.pop_front(); return; }
        ++input.phase;
    }
    void set_page(Page page) {
        if (page_ == page) return; hold_.cancel(); page_ = page;
        if (page_ != Page::diagnostics) { references_.clear(); expanded_.clear(); children_.clear(); shown_.reset(); }
    }
    NodeId first_detector() const {
        for (const auto& node : session_.engine.state()->topology->nodes) if (node.kind == NodeKind::detector) return node.id;
        return 0;
    }
    void apply_style() {
        ImGui::GetStyle() = base_style_;
        if (dark_) ImGui::StyleColorsDark(); else ImGui::StyleColorsLight();
        ImGui::GetStyle().ScaleAllSizes(dpi_); ImGui::GetStyle().FontScaleDpi = dpi_;
    }
    void draw_monitor() {
        if (preview_.view) {
            const float width = std::max(240.0f, ImGui::GetContentRegionAvail().x * .48f);
            ImGui::BeginChild("preview", {width, 0}); draw_image(preview_, {width, width * 9 / 16}); ImGui::EndChild();
            ImGui::SameLine();
        }
        ImGui::BeginChild("scenario-cards", {0, 0}, ImGuiChildFlags_Borders);
        for (std::size_t i = 0; i < display_->topology->nodes.size(); ++i) if (display_->topology->nodes[i].kind == NodeKind::scenario) {
            const auto& node = display_->topology->nodes[i]; const auto& metric = display_->metrics[i];
            ImGui::PushID(reinterpret_cast<void*>(std::uintptr_t(node.id)));
            ImGui::BeginChild("card", {0, 70 * dpi_}, ImGuiChildFlags_Borders);
            ImGui::TextUnformatted(node.label.c_str()); ImGui::Text("%s | %.3f", metric.connected ? "Connected" : "Disconnected", metric.score);
            ImGui::EndChild(); ImGui::PopID();
        }
        ImGui::EndChild();
    }
    void draw_node(std::size_t index) {
        const auto& node = shown_->nodes[index]; const auto& metric = display_->metrics[index];
        ImGui::TableNextRow(); ImGui::TableNextColumn(); ImGui::PushID(reinterpret_cast<void*>(std::uintptr_t(node.id)));
        if (auto found = open_requests_.find(node.id); found != open_requests_.end()) {
            ImGui::SetNextItemOpen(found->second, ImGuiCond_Always); open_requests_.erase(found);
        }
        const bool open = ImGui::TreeNodeEx("node", ImGuiTreeNodeFlags_SpanAllColumns, "%s", node.label.c_str());
        ImGui::TableNextColumn(); ImGui::Text("%.3f %s", metric.score, metric.active ? "active" : "waiting");
        if (open) {
            expanded_.insert(node.id);
            if (node.kind == NodeKind::detector) {
                wanted_references_.insert(node.id);
                if (!references_.contains(node.id)) references_.emplace(node.id, texture(reference_image(session_.engine, node.id)));
                ImGui::TableNextRow(); ImGui::TableNextColumn(); ImGui::TextUnformatted("Reference shown below");
            } else for (auto child : children_[node.id]) draw_node(child);
            ImGui::TreePop();
        }
        ImGui::PopID();
    }
    void draw_diagnostics() {
        if (shown_ != display_->topology) {
            shown_ = display_->topology; children_.clear();
            for (std::size_t i = 0; i < shown_->nodes.size(); ++i) children_[shown_->nodes[i].parent].push_back(i);
            ++session_.counters.topology_builds;
        }
        expanded_.clear(); wanted_references_.clear();
        if (ImGui::BeginTable("diagnostic-tree", 2, ImGuiTableFlags_Borders | ImGuiTableFlags_ScrollY | ImGuiTableFlags_Resizable, {0, -120 * dpi_})) {
            ImGui::TableSetupColumn("Scenario / Rule / Condition / Detector"); ImGui::TableSetupColumn("Score / state"); ImGui::TableHeadersRow();
            if (scroll_request_) { ImGui::SetScrollY(32 * dpi_); scroll_request_ = false; }
            for (auto root : children_[0]) draw_node(root);
            scroll_ = int(ImGui::GetScrollY()); ImGui::EndTable();
        }
        std::erase_if(references_, [this](const auto& pair) { return !wanted_references_.contains(pair.first); });
        ImGui::BeginChild("reference-images", {0, 0}, ImGuiChildFlags_None, ImGuiWindowFlags_HorizontalScrollbar);
        bool first = true;
        for (const auto& pair : references_) { if (!first) ImGui::SameLine(); draw_image(pair.second, {160 * dpi_, 90 * dpi_}); first = false; }
        ImGui::EndChild();
    }
    void browse() {
        CancelNativeDialog cancel(cancel_file_); cancel_file_ = false;
        ComPtr<IFileOpenDialog> dialog; checked(CoCreateInstance(CLSID_FileOpenDialog, nullptr, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&dialog)), "File dialog creation failed");
        dialog->SetTitle(L"Select mock input source");
        const auto result = dialog->Show(hwnd_);
        if (result == HRESULT_FROM_WIN32(ERROR_CANCELLED)) { ++file_cancels_; return; }
        checked(result, "File dialog failed");
        ComPtr<IShellItem> item; checked(dialog->GetResult(&item), "File result failed");
        PWSTR raw = nullptr; checked(item->GetDisplayName(SIGDN_FILESYSPATH, &raw), "File path failed");
        const auto path = std::filesystem::path(raw).u8string(); CoTaskMemFree(raw);
        session_.profile.draft.file.assign(path.begin(), path.end()); session_.profile.draft.source = Source::synthetic_file;
    }
    bool confirm_discard() {
        CancelNativeDialog cancel(cancel_discard_); cancel_discard_ = false;
        const auto result = MessageBoxW(hwnd_, L"Discard unapplied changes?", L"Unsaved Profile", MB_OKCANCEL | MB_DEFBUTTON2 | MB_ICONQUESTION);
        if (result == IDCANCEL) ++discard_cancels_; return result == IDOK;
    }
    void draw_profile() {
        auto& draft = session_.profile.draft;
        int source = int(draft.source); if (ImGui::Combo("Input source", &source, "Synthetic camera\0Synthetic file\0")) draft.source = Source(source);
        ImGui::InputText("File path", &draft.file); ImGui::SameLine(); button("Browse...", [this] { browse(); });
        if (ImGui::BeginTable("profile-rows", 3, ImGuiTableFlags_Borders | ImGuiTableFlags_ScrollY, {0, -80 * dpi_})) {
            ImGui::TableSetupColumn("Scenario"); ImGui::TableSetupColumn("Port"); ImGui::TableSetupColumn("Selection"); ImGui::TableHeadersRow();
            for (std::size_t i = 0; i < draft.scenarios.size(); ++i) {
                auto& value = draft.scenarios[i]; ImGui::PushID(reinterpret_cast<void*>(std::uintptr_t(value.id)));
                ImGui::TableNextRow(); ImGui::TableNextColumn(); ImGui::SetNextItemWidth(-1);
                ImGui::InputText("##name", &value.name); if (!i) remember("Name");
                ImGui::TableNextColumn(); ImGui::SetNextItemWidth(-1); ImGui::InputInt("##port", &value.port);
                ImGui::TableNextColumn(); if (ImGui::Selectable("Select", selected_ == value.id)) selected_ = value.id;
                ImGui::PopID();
            }
            ImGui::EndTable();
        }
        button("Add Scenario", [this] { session_.profile.add_scenario(); selected_ = session_.profile.draft.scenarios.back().id; }); ImGui::SameLine();
        button("Remove Scenario", [this] { if (selected_) session_.profile.remove_scenario(selected_); }); ImGui::SameLine();
        button("Apply", [this] {
            auto errors = session_.profile.apply(); if (errors.empty()) errors = session_.engine.apply_profile(session_.profile.applied());
            error_.clear(); for (const auto& error : errors) error_ += error + "; ";
        }); ImGui::SameLine();
        button("Discard", [this] { session_.profile.discard(); error_.clear(); }); ImGui::SameLine();
        button("New Profile", [this] { if (!session_.profile.dirty() || confirm_discard()) session_.profile.draft = Profile{}; });
        ImGui::TextWrapped("%s", error_.c_str());
    }
    void draw() {
        const auto now = std::chrono::steady_clock::now();
        if (cadence_.due(now)) {
            display_ = session_.engine.state();
            if (page_ == Page::monitor) if (auto frame = session_.engine.frame(); frame && frame->sequence != session_.counters.last_frame) {
                preview_ = texture(frame->image); session_.observe_frame(*frame);
            }
            if (page_ == Page::diagnostics) ++session_.counters.value_updates;
        }
        if (!display_) display_ = session_.engine.state();
        ImGui::SetNextWindowPos({0, 0}); ImGui::SetNextWindowSize(ImGui::GetIO().DisplaySize);
        ImGui::Begin("DivergenceSplitter", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings);
        button("Start", [this] { session_.engine.set_running(true); }); ImGui::SameLine();
        button("Stop", [this] { hold_.cancel(); session_.engine.set_running(false); }); ImGui::SameLine();
        ImGui::Button("Reset All"); remember("Reset All");
        if (ImGui::IsItemActivated()) hold_.press(now);
        if (ImGui::IsItemDeactivated()) hold_.cancel();
        if (hold_.poll(now)) session_.engine.reset_all();
        ImGui::SameLine(); ImGui::Text("%d%%", int(hold_.progress(now) * 100)); ImGui::SameLine();
        button("Mutate", [this] { if (!session_.engine.mutate_topology()) error_ = "Topology input busy"; }); ImGui::SameLine();
        button("Light / dark", [this] { dark_ = !dark_; apply_style(); });
        ImGui::Text("%s | sequence %llu | reset %llu", display_->running ? "Running" : "Stopped",
            static_cast<unsigned long long>(display_->sequence), static_cast<unsigned long long>(display_->resets));
        button("Monitor", [this] { set_page(Page::monitor); }); ImGui::SameLine();
        button("Diagnostics", [this] { set_page(Page::diagnostics); }); ImGui::SameLine();
        button("Profile", [this] { set_page(Page::profile); }); ImGui::Separator();
        if (page_ == Page::monitor) draw_monitor(); else if (page_ == Page::diagnostics) draw_diagnostics(); else draw_profile();
        ImGui::End(); session_.sample_process(); session_.exercise(*this);
    }
    void capture() {
        if (session_.options.capture.empty()) return;
        ComPtr<ID3D11Texture2D> buffer; checked(swapchain_->GetBuffer(0, IID_PPV_ARGS(&buffer)), "Capture buffer failed");
        D3D11_TEXTURE2D_DESC description{}; buffer->GetDesc(&description);
        description.BindFlags = 0; description.MiscFlags = 0; description.Usage = D3D11_USAGE_STAGING; description.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        ComPtr<ID3D11Texture2D> staging; checked(device_->CreateTexture2D(&description, nullptr, &staging), "Capture staging failed");
        context_->CopyResource(staging.Get(), buffer.Get()); D3D11_MAPPED_SUBRESOURCE mapped{};
        checked(context_->Map(staging.Get(), 0, D3D11_MAP_READ, 0, &mapped), "Capture map failed");
        Image result{description.Width, description.Height, std::vector<std::uint8_t>(std::size_t(description.Width) * description.Height * 4)};
        for (std::uint32_t y = 0; y < result.height; ++y) std::copy_n(static_cast<std::uint8_t*>(mapped.pData) + std::size_t(y) * mapped.RowPitch, std::size_t(result.width) * 4, result.rgba.data() + std::size_t(y) * result.width * 4);
        context_->Unmap(staging.Get(), 0); save_png(result, session_.options.capture);
    }
    Session& session_; ContractScript script_; ResetHold hold_; PreviewCadence cadence_;
    HWND hwnd_{}; ComPtr<ID3D11Device> device_; ComPtr<ID3D11DeviceContext> context_;
    ComPtr<IDXGISwapChain> swapchain_; ComPtr<ID3D11RenderTargetView> target_;
    Texture preview_; std::unordered_map<NodeId, Texture> references_;
    std::unordered_map<NodeId, std::vector<std::size_t>> children_;
    std::unordered_map<NodeId, bool> open_requests_; std::unordered_set<NodeId> expanded_, wanted_references_;
    std::unordered_map<std::string, ImVec4> rectangles_; std::deque<Input> input_;
    std::shared_ptr<const State> display_; std::shared_ptr<const Topology> shown_;
    Page page_ = Page::monitor; std::string error_; ImGuiStyle base_style_;
    NodeId selected_ = 0; float dpi_ = 1; int scroll_ = 0;
    bool quit_ = false, dark_ = false, cancel_file_ = false, cancel_discard_ = false, scroll_request_ = false;
    unsigned file_cancels_ = 0, discard_cancels_ = 0;
};
}
int main(int argc, char** argv) {
    const auto com = CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);
    try {
        int result;
        { Session session(Options::parse(argc, argv), "imgui"); Window window(session); result = window.run(); }
        if (SUCCEEDED(com)) CoUninitialize(); return result;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; if (SUCCEEDED(com)) CoUninitialize(); return 1; }
}
