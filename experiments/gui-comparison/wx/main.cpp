#include "app.hpp"
#include "dialog_test.hpp"
#include <wx/wx.h>
#include <wx/choice.h>
#include <wx/filedlg.h>
#include <wx/dataview.h>
#include <wx/grid.h>
#include <wx/notebook.h>
#include <wx/scrolwin.h>
#include <wx/statbmp.h>
#include <wx/treelist.h>
#include <wx/dcmemory.h>
#include <wx/dcclient.h>
#include <algorithm>
#include <iostream>
#include <unordered_map>
#include <unordered_set>

using namespace comparison;
namespace {
wxString text(const std::string& value) { return wxString::FromUTF8(value); }
wxImage image(const Image& value) {
    wxImage result(int(value.width), int(value.height));
    result.InitAlpha();
    for (std::size_t i = 0; i < std::size_t(value.width) * value.height; ++i) {
        std::copy_n(value.rgba.data() + i * 4, 3, result.GetData() + i * 3);
        result.GetAlpha()[i] = value.rgba[i * 4 + 3];
    }
    return result;
}
class IdData : public wxClientData {
public: explicit IdData(NodeId value) : id(value) {} NodeId id;
};
class Window final : public wxFrame, public Driver {
public:
    explicit Window(Session& session) : wxFrame(nullptr, wxID_ANY, "DivergenceSplitter comparison - wxWidgets", wxDefaultPosition, {1100, 760}),
        session_(session), script_(session), timer_(this) {
        auto root = new wxPanel(this); auto layout = new wxBoxSizer(wxVERTICAL);
        auto toolbar = new wxBoxSizer(wxHORIZONTAL);
        button(root, toolbar, "Start", [this] { session_.engine.set_running(true); });
        button(root, toolbar, "Stop", [this] { cancel_hold(); session_.engine.set_running(false); });
        reset_ = new wxButton(root, wxID_ANY, "Hold 2s: Reset All"); toolbar->Add(reset_, 0, wxALL, 3);
        reset_->Bind(wxEVT_LEFT_DOWN, [this](wxMouseEvent&) { hold_.press(std::chrono::steady_clock::now()); if (!reset_->HasCapture()) reset_->CaptureMouse(); });
        reset_->Bind(wxEVT_LEFT_UP, [this](wxMouseEvent&) { cancel_hold(); });
        reset_->Bind(wxEVT_MOUSE_CAPTURE_LOST, [this](wxMouseCaptureLostEvent&) { hold_.cancel(); });
        reset_->Bind(wxEVT_KILL_FOCUS, [this](wxFocusEvent& event) { cancel_hold(); event.Skip(); });
        mutate_ = button(root, toolbar, "Add/remove diagnostic branch", [this] { if (!session_.engine.mutate_topology()) status_->SetLabel("Topology input busy"); });
        theme_ = button(root, toolbar, "Light / dark", [this] { dark_ = !dark_; wxTheApp->SetAppearance(dark_ ? wxApp::Appearance::Dark : wxApp::Appearance::Light); });
        layout->Add(toolbar, 0, wxEXPAND);
        status_ = new wxStaticText(root, wxID_ANY, "Starting"); layout->Add(status_, 0, wxEXPAND | wxALL, 5);
        tabs_ = new wxNotebook(root, wxID_ANY); layout->Add(tabs_, 1, wxEXPAND | wxALL, 5);
        build_monitor(); build_diagnostics(); build_profile();
        tabs_->Bind(wxEVT_NOTEBOOK_PAGE_CHANGED, [this](wxBookCtrlEvent& event) {
            cancel_hold(); if (tabs_->GetSelection() != 1) release_diagnostics(); else sync_tree(); event.Skip();
        });
        root->SetSizer(layout);
        Bind(wxEVT_TIMER, [this](wxTimerEvent&) { tick(); });
        Bind(wxEVT_ACTIVATE, [this](wxActivateEvent& event) { if (!event.GetActive()) cancel_hold(); event.Skip(); });
        Bind(wxEVT_CLOSE_WINDOW, [this](wxCloseEvent& event) {
            cancel_hold();
            if (!finishing_ && event.CanVeto() && session_.profile.dirty() && !confirm_discard()) { event.Veto(); return; }
            timer_.Stop(); release_diagnostics(); session_.engine.stop(); Destroy();
        });
        timer_.Start(67);
        session_.renderer = "wxWidgets MSW / wxTreeListCtrl";
    }
    Probe probe() const override {
        Probe p; p.page = Page(tabs_->GetSelection()); p.dirty = session_.profile.dirty();
        p.errors = !error_->GetLabel().empty(); p.references = references_.size();
        p.draft_count = session_.profile.draft.scenarios.size(); tree_->GetDataView()->GetViewStart(nullptr, &p.scroll);
        p.file_cancels = file_cancels_; p.discard_cancels = discard_cancels_;
        if (items_.contains(first_detector())) p.expanded = tree_->IsExpanded(items_.at(first_detector()));
        return p;
    }
    void perform(Action action) override {
        auto click = [](wxButton* button) { wxCommandEvent event(wxEVT_BUTTON, button->GetId()); event.SetEventObject(button); button->GetEventHandler()->ProcessEvent(event); };
        auto name = [this](const wxString& value) {
            grid_->SetCellValue(0, 0, value);
            wxGridEvent event(grid_->GetId(), wxEVT_GRID_CELL_CHANGED, grid_, 0, 0);
            grid_->GetEventHandler()->ProcessEvent(event);
        };
        auto enabled = [this](bool value) {
            grid_->SetCellValue(0, 2, value ? "1" : "");
            wxGridEvent event(grid_->GetId(), wxEVT_GRID_CELL_CHANGED, grid_, 0, 2);
            grid_->GetEventHandler()->ProcessEvent(event);
        };
        switch (action) {
        case Action::monitor: tabs_->SetSelection(0); break;
        case Action::diagnostics: tabs_->SetSelection(1); break;
        case Action::profile: tabs_->SetSelection(2); break;
        case Action::expand: {
            auto found = items_.find(first_detector()); if (found == items_.end()) break;
            std::vector<wxTreeListItem> path;
            for (auto item = found->second; item.IsOk() && item != tree_->GetRootItem(); item = tree_->GetItemParent(item)) path.push_back(item);
            for (auto it = path.rbegin(); it != path.rend(); ++it) tree_->Expand(*it);
            refresh_references(); break;
        }
        case Action::collapse: if (items_.contains(first_detector())) tree_->Collapse(items_.at(first_detector())); refresh_references(); break;
        case Action::mutate: click(mutate_); break;
        case Action::invalid_draft: name(""); break;
        case Action::valid_draft: name("Edited scenario"); enabled(false); break;
        case Action::apply: click(apply_); break;
        case Action::add_scenario: click(add_); break;
        case Action::remove_scenario: grid_->SetGridCursor(grid_->GetNumberRows() - 1, 0); click(remove_); break;
        case Action::file_cancel: {
            auto before = session_.profile.draft; CancelNativeDialog cancel(true); click(browse_);
            if (session_.profile.draft != before) throw std::runtime_error("File cancel changed draft"); break;
        }
        case Action::unsaved_cancel: {
            enabled(true); CancelNativeDialog cancel(true); click(fresh_); break;
        }
        case Action::discard: click(discard_); break;
        case Action::reset_press: { wxMouseEvent event(wxEVT_LEFT_DOWN); event.SetEventObject(reset_); reset_->GetEventHandler()->ProcessEvent(event); break; }
        case Action::reset_release: { wxMouseEvent event(wxEVT_LEFT_UP); event.SetEventObject(reset_); reset_->GetEventHandler()->ProcessEvent(event); break; }
        case Action::reset_cancel: { wxFocusEvent event(wxEVT_KILL_FOCUS, reset_->GetId()); reset_->GetEventHandler()->ProcessEvent(event); break; }
        case Action::theme: click(theme_); break;
        case Action::resize: SetSize({800, 600}); break;
        case Action::start: session_.engine.set_running(true); break;
        case Action::stop: hold_.cancel(); session_.engine.set_running(false); break;
        case Action::scroll:
            for (const auto& node : session_.engine.state()->topology->nodes)
                if (node.kind == NodeKind::scenario && !tree_->IsExpanded(items_.at(node.id))) tree_->Expand(items_.at(node.id));
            CallAfter([this] { tree_->GetDataView()->Scroll(0, 2); }); break;
        }
    }
private:
    template<class F> wxButton* button(wxWindow* parent, wxSizer* row, const char* title, F callback) {
        auto result = new wxButton(parent, wxID_ANY, title); row->Add(result, 0, wxALL, 3);
        result->Bind(wxEVT_BUTTON, [callback = std::move(callback)](wxCommandEvent&) { callback(); }); return result;
    }
    void cancel_hold() { hold_.cancel(); if (reset_ && reset_->HasCapture()) reset_->ReleaseMouse(); }
    void build_monitor() {
        auto page = new wxPanel(tabs_); auto row = new wxBoxSizer(wxHORIZONTAL);
        preview_ = new wxStaticBitmap(page, wxID_ANY, wxBitmap(320, 180)); preview_->SetMinSize({320, 180});
        row->Add(preview_, 1, wxALL | wxALIGN_CENTER_VERTICAL, 5);
        cards_ = new wxScrolledWindow(page); cards_->SetScrollRate(0, 10); card_layout_ = new wxBoxSizer(wxVERTICAL); cards_->SetSizer(card_layout_);
        row->Add(cards_, 1, wxEXPAND | wxALL, 5); page->SetSizer(row); tabs_->AddPage(page, "Monitor");
    }
    void build_diagnostics() {
        auto page = new wxPanel(tabs_); auto layout = new wxBoxSizer(wxVERTICAL);
        tree_ = new wxTreeListCtrl(page, wxID_ANY); tree_->AppendColumn("Scenario / Rule / Condition / Detector", 560);
        tree_->AppendColumn("Score / state", 180); layout->Add(tree_, 1, wxEXPAND);
        reference_panel_ = new wxScrolledWindow(page); reference_panel_->SetScrollRate(10, 0); reference_panel_->SetMinSize({200, 110});
        reference_layout_ = new wxBoxSizer(wxHORIZONTAL); reference_panel_->SetSizer(reference_layout_);
        layout->Add(reference_panel_, 0, wxEXPAND); page->SetSizer(layout); tabs_->AddPage(page, "Diagnostics");
        tree_->Bind(wxEVT_TREELIST_ITEM_EXPANDED, [this](wxTreeListEvent&) { refresh_references(); });
        // TreeList forwards expansion but not collapse; use its documented view.
        tree_->GetView()->Bind(wxEVT_DATAVIEW_ITEM_COLLAPSED, [this](wxDataViewEvent& event) {
            event.Skip(); CallAfter([this] { refresh_references(); });
        });
    }
    void build_profile() {
        auto page = new wxPanel(tabs_); auto layout = new wxBoxSizer(wxVERTICAL); auto row = new wxBoxSizer(wxHORIZONTAL);
        source_ = new wxChoice(page, wxID_ANY); source_->Append("Synthetic camera"); source_->Append("Synthetic file"); row->Add(source_, 0, wxALL, 3);
        file_ = new wxTextCtrl(page, wxID_ANY); row->Add(file_, 1, wxALL, 3);
        browse_ = button(page, row, "Browse...", [this] {
            wxFileDialog dialog(this, "Select mock input source", {}, {}, "Video files (*.avi;*.mp4)|*.avi;*.mp4|All files|*.*", wxFD_OPEN | wxFD_FILE_MUST_EXIST);
            if (dialog.ShowModal() == wxID_OK) { source_->SetSelection(1); session_.profile.draft.source = Source::synthetic_file; file_->SetValue(dialog.GetPath()); }
            else ++file_cancels_;
        });
        layout->Add(row, 0, wxEXPAND);
        grid_ = new wxGrid(page, wxID_ANY); grid_->CreateGrid(0, 3); grid_->SetColLabelValue(0, "Scenario name"); grid_->SetColLabelValue(1, "Port");
        grid_->SetColLabelValue(2, "Enabled"); grid_->SetColFormatBool(2); grid_->SetColSize(2, 100);
        grid_->SetColSize(0, 380); grid_->SetColSize(1, 160); layout->Add(grid_, 1, wxEXPAND | wxALL, 3);
        auto buttons = new wxBoxSizer(wxHORIZONTAL);
        add_ = button(page, buttons, "Add Scenario", [this] { session_.profile.add_scenario(); sync_form(); grid_->SetGridCursor(grid_->GetNumberRows() - 1, 0); });
        remove_ = button(page, buttons, "Remove Scenario", [this] {
            auto row = grid_->GetGridCursorRow(); if (row >= 0 && row < int(session_.profile.draft.scenarios.size())) {
                session_.profile.remove_scenario(session_.profile.draft.scenarios[std::size_t(row)].id); sync_form();
            }
        });
        apply_ = button(page, buttons, "Apply", [this] {
            grid_->SaveEditControlValue();
            auto errors = session_.profile.apply(); if (errors.empty()) errors = session_.engine.apply_profile(session_.profile.applied());
            std::string message; for (const auto& error : errors) message += error + "; "; error_->SetLabel(text(message));
        });
        discard_ = button(page, buttons, "Discard", [this] { session_.profile.discard(); sync_form(); error_->SetLabel(""); });
        fresh_ = button(page, buttons, "New Profile", [this] {
            if (!session_.profile.dirty() || confirm_discard()) { session_.profile.draft = Profile{}; sync_form(); }
        });
        layout->Add(buttons, 0, wxEXPAND); error_ = new wxStaticText(page, wxID_ANY, ""); layout->Add(error_, 0, wxEXPAND | wxALL, 3);
        source_->Bind(wxEVT_CHOICE, [this](wxCommandEvent&) { if (!syncing_) session_.profile.draft.source = Source(source_->GetSelection()); });
        file_->Bind(wxEVT_TEXT, [this](wxCommandEvent&) { if (!syncing_) session_.profile.draft.file = file_->GetValue().ToStdString(wxConvUTF8); });
        grid_->Bind(wxEVT_GRID_CELL_CHANGED, [this](wxGridEvent& event) {
            if (syncing_) return;
            auto& value = session_.profile.draft.scenarios.at(std::size_t(event.GetRow()));
            if (event.GetCol() == 0) value.name = grid_->GetCellValue(event.GetRow(), 0).ToStdString(wxConvUTF8);
            else if (event.GetCol() == 1) { long port = 0; grid_->GetCellValue(event.GetRow(), 1).ToLong(&port); value.port = int(port); }
            else value.enabled = grid_->GetCellValue(event.GetRow(), 2) == "1";
        });
        page->SetSizer(layout); tabs_->AddPage(page, "Profile"); sync_form();
    }
    void sync_form() {
        syncing_ = true; source_->SetSelection(int(session_.profile.draft.source)); file_->ChangeValue(text(session_.profile.draft.file));
        const auto count = int(session_.profile.draft.scenarios.size());
        if (grid_->GetNumberRows() < count) grid_->AppendRows(count - grid_->GetNumberRows());
        else if (grid_->GetNumberRows() > count) grid_->DeleteRows(count, grid_->GetNumberRows() - count);
        for (int i = 0; i < count; ++i) {
            const auto& value = session_.profile.draft.scenarios[std::size_t(i)];
            grid_->SetCellValue(i, 0, text(value.name)); grid_->SetCellValue(i, 1, wxString::Format("%d", value.port));
            grid_->SetCellValue(i, 2, value.enabled ? "1" : "");
        }
        syncing_ = false;
    }
    bool confirm_discard() {
        wxMessageDialog dialog(this, "Discard unapplied changes?", "Unsaved Profile", wxOK | wxCANCEL | wxCANCEL_DEFAULT);
        dialog.SetOKLabel("Discard"); const auto answer = dialog.ShowModal();
        if (answer == wxID_CANCEL) ++discard_cancels_;
        return answer == wxID_OK;
    }
    NodeId first_detector() const {
        for (const auto& node : session_.engine.state()->topology->nodes) if (node.kind == NodeKind::detector) return node.id;
        return 0;
    }
    bool ancestors_expanded(wxTreeListItem item, bool include_self) const {
        if (!include_self) item = tree_->GetItemParent(item);
        for (; item.IsOk() && item != tree_->GetRootItem(); item = tree_->GetItemParent(item)) if (!tree_->IsExpanded(item)) return false;
        return true;
    }
    void refresh_references() {
        if (tabs_->GetSelection() != 1 || !shown_) return;
        std::unordered_set<NodeId> wanted;
        for (const auto& node : shown_->nodes) {
            if (node.kind != NodeKind::detector || !ancestors_expanded(items_.at(node.id), true)) continue;
            wanted.insert(node.id);
            if (!references_.contains(node.id)) {
                auto bitmap = new wxStaticBitmap(reference_panel_, wxID_ANY, wxBitmap(image(reference_image(session_.engine, node.id))));
                reference_layout_->Add(bitmap, 0, wxALL, 3); references_[node.id] = bitmap;
            }
        }
        std::erase_if(references_, [&](auto& pair) { if (wanted.contains(pair.first)) return false; reference_layout_->Detach(pair.second); pair.second->Destroy(); return true; });
        reference_panel_->FitInside(); reference_panel_->Layout();
    }
    void release_diagnostics() {
        for (auto& pair : references_) { reference_layout_->Detach(pair.second); pair.second->Destroy(); }
        references_.clear(); tree_->DeleteAllItems(); items_.clear(); shown_.reset();
    }
    void erase_items(wxTreeListItem item) {
        if (auto data = static_cast<IdData*>(tree_->GetItemData(item))) items_.erase(data->id);
        for (auto child = tree_->GetFirstChild(item); child.IsOk(); child = tree_->GetNextSibling(child)) erase_items(child);
    }
    void sync_tree() {
        auto state = session_.engine.state(); if (shown_ == state->topology) return;
        ++session_.counters.topology_builds; tree_->Freeze();
        std::unordered_set<NodeId> wanted; for (const auto& node : state->topology->nodes) wanted.insert(node.id);
        if (shown_) for (const auto& node : shown_->nodes) {
            if (wanted.contains(node.id) || (node.parent && !wanted.contains(node.parent))) continue;
            auto item = items_.at(node.id); erase_items(item); tree_->DeleteItem(item);
        }
        for (const auto& node : state->topology->nodes) {
            if (items_.contains(node.id)) { tree_->SetItemText(items_.at(node.id), text(node.label)); continue; }
            auto parent = node.parent ? items_.at(node.parent) : tree_->GetRootItem();
            auto item = tree_->AppendItem(parent, text(node.label), -1, -1, new IdData(node.id)); items_[node.id] = item;
            if (node.kind == NodeKind::detector) tree_->AppendItem(item, "Reference shown below");
        }
        shown_ = state->topology; tree_->Thaw(); refresh_references();
    }
    void update_values(const State& state) {
        tree_->Freeze();
        for (const auto& metric : state.metrics) if (items_.contains(metric.id) && ancestors_expanded(items_.at(metric.id), false)) {
            tree_->SetItemText(items_.at(metric.id), 1, text(score_text(metric.score) + (!metric.enabled ? " disabled" : metric.active ? " active" : " waiting")));
        }
        tree_->Thaw(); ++session_.counters.value_updates;
    }
    void capture() {
        if (session_.options.capture.empty()) return;
        auto size = GetClientSize(); wxBitmap bitmap(size.x, size.y); wxMemoryDC destination(bitmap); wxClientDC source(this);
        destination.Blit(0, 0, size.x, size.y, &source, 0, 0); destination.SelectObject(wxNullBitmap);
        if (!bitmap.SaveFile(text(session_.options.capture.string()), wxBITMAP_TYPE_PNG)) throw std::runtime_error("Window capture failed");
    }
    void tick() {
        try {
            auto now = std::chrono::steady_clock::now(); if (hold_.poll(now)) session_.engine.reset_all();
            reset_->SetLabel(text("Reset All " + std::to_string(int(hold_.progress(now) * 100)) + "%"));
            auto state = session_.engine.state(); status_->SetLabel(text(std::string(state->running ? "Running" : "Stopped") + " | sequence " + std::to_string(state->sequence) + " | reset " + std::to_string(state->resets)));
            if (tabs_->GetSelection() == 0) {
                if (auto frame = session_.engine.frame()) { preview_->SetBitmap(wxBitmap(image(frame->image).Scale(480, 270, wxIMAGE_QUALITY_HIGH))); session_.observe_frame(*frame); }
                if (cards_topology_ != state->topology) {
                    card_layout_->Clear(true); card_labels_.clear();
                    for (const auto& scenario : state->applied_profile->scenarios) {
                        (void)scenario; auto label = new wxStaticText(cards_, wxID_ANY, "", wxDefaultPosition, {200, 65}, wxBORDER_SIMPLE);
                        card_layout_->Add(label, 0, wxEXPAND | wxALL, 4); card_labels_.push_back(label);
                    }
                    cards_topology_ = state->topology; cards_->FitInside(); cards_->Layout();
                }
                std::size_t card = 0;
                for (std::size_t i = 0; i < state->topology->nodes.size(); ++i) if (state->topology->nodes[i].kind == NodeKind::scenario) {
                    auto& metric = state->metrics[i]; card_labels_.at(card++)->SetLabel(text(state->topology->nodes[i].label + "\n" + (!metric.enabled ? "Disabled" : metric.connected ? "Connected" : "Disconnected") + " | " + score_text(metric.score)));
                }
            } else if (tabs_->GetSelection() == 1) { sync_tree(); update_values(*state); }
            session_.sample_process(); session_.exercise(*this);
            if ((session_.options.self_test && script_.tick(*this)) || session_.expired()) finish();
        } catch (const std::exception& error) { session_.error = error.what(); finish(); }
    }
    void finish() {
        if (finishing_) return; finishing_ = true; timer_.Stop(); cancel_hold();
        try { capture(); } catch (const std::exception& error) { session_.error = error.what(); }
        release_diagnostics(); session_.engine.stop();
        try { session_.write_report(); } catch (const std::exception& error) { session_.error = error.what(); std::cerr << error.what() << '\n'; }
        Close(true);
    }
    Session& session_; ContractScript script_; ResetHold hold_; wxTimer timer_;
    wxNotebook* tabs_{}; wxStaticText *status_{}, *error_{}; wxStaticBitmap* preview_{};
    wxScrolledWindow *cards_{}, *reference_panel_{}; wxBoxSizer *card_layout_{}, *reference_layout_{};
    std::vector<wxStaticText*> card_labels_; wxTreeListCtrl* tree_{}; wxGrid* grid_{}; wxChoice* source_{}; wxTextCtrl* file_{};
    wxButton *reset_{}, *mutate_{}, *theme_{}, *apply_{}, *add_{}, *remove_{}, *browse_{}, *discard_{}, *fresh_{};
    std::unordered_map<NodeId, wxTreeListItem> items_; std::unordered_map<NodeId, wxStaticBitmap*> references_;
    std::shared_ptr<const Topology> shown_, cards_topology_;
    bool syncing_ = false, finishing_ = false, dark_ = false;
    unsigned file_cancels_ = 0, discard_cancels_ = 0;
};
Session* active_session = nullptr;
class App : public wxApp {
public:
    bool OnInit() override { wxInitAllImageHandlers(); auto window = new Window(*active_session); SetTopWindow(window); window->Show(); return true; }
};
}
wxIMPLEMENT_APP_NO_MAIN(App);
int main(int argc, char** argv) {
    try {
        Session session(Options::parse(argc, argv), "wx"); active_session = &session;
        int toolkit_argc = 1; char* toolkit_argv[]{argv[0], nullptr};
        const auto result = wxEntry(toolkit_argc, toolkit_argv);
        return session.error.empty() ? result : 1;
    } catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 1; }
}
