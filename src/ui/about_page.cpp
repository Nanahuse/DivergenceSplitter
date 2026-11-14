#include "about_page.hpp"

#include <imgui.h>

#include <filesystem>
#include <string>

#include "license_inventory.hpp"
#include "ui_helpers.hpp"

namespace divergencesplitter::ui {
namespace {

void draw_details(const LicenseComponent& component) {
    if (!component.license_file.empty()) {
        const std::string relative = "licenses/" + component.license_file;
        if (std::filesystem::is_regular_file(application_directory() / relative)) {
            if (ImGui::SmallButton(("License##" + component.name).c_str())) {
                (void)open_file(relative);
            }
        } else {
            text_muted("Not bundled in this build");
        }
    } else if (!component.url.empty()) {
        const std::string label = "License##" + component.name;
        ImGui::TextLinkOpenURL(label.c_str(), component.url.c_str());
    } else {
        text_muted("-");
    }
}

}  // namespace

AboutPage::AboutPage()
    : inventory_(load_license_inventory()),
      additional_notices_(license_notice_files(inventory_ ? &*inventory_ : nullptr)) {}

void AboutPage::draw() {
    ImGui::Dummy(ImVec2(0.0f, 8.0f));
    ImGui::Indent(16.0f);
    ImGui::TextUnformatted("DivergenceSplitter");
    text_muted("Version " DIVERGENCESPLITTER_VERSION);
    ImGui::TextLinkOpenURL("GitHub", "https://github.com/Nanahuse/DivergenceSplitter");

    ImGui::Spacing();
    ImGui::Separator();
    ImGui::Spacing();

    ImGui::BeginChild("##about_scroll", ImVec2(0.0f, 0.0f), false);
    ImGui::Indent(16.0f);

    ImGui::SeparatorText("Application license");
    if (inventory_.has_value()) {
        ImGui::Text("DivergenceSplitter - %s", inventory_->application_license.c_str());
        const auto relative = inventory_->application_license_file;
        if (std::filesystem::is_regular_file(application_directory() / relative)) {
            if (ImGui::SmallButton("License##application")) {
                (void)open_file(relative);
            }
        } else {
            text_muted("Not bundled in this build");
        }
    } else {
        ImGui::TextUnformatted("DivergenceSplitter - MIT");
    }

    ImGui::Spacing();
    ImGui::SeparatorText("Third-party Components");
    if (!inventory_.has_value()) {
        text_muted("License inventory is not available in this build.");
    } else if (ImGui::BeginTable(
                   "##components",
                   3,
                   ImGuiTableFlags_Borders | ImGuiTableFlags_RowBg |
                       ImGuiTableFlags_SizingStretchProp
               )) {
        ImGui::TableSetupColumn("Component", ImGuiTableColumnFlags_WidthStretch);
        ImGui::TableSetupColumn("License", ImGuiTableColumnFlags_WidthFixed, 260.0f);
        ImGui::TableSetupColumn("Details", ImGuiTableColumnFlags_WidthFixed, 90.0f);
        ImGui::TableHeadersRow();
        for (const auto& component : inventory_->components) {
            ImGui::TableNextRow();
            ImGui::TableNextColumn();
            ImGui::TextUnformatted(component.name.c_str());
            ImGui::TableNextColumn();
            ImGui::TextUnformatted(component.license.c_str());
            ImGui::TableNextColumn();
            draw_details(component);
        }
        ImGui::EndTable();
    }

    ImGui::Spacing();
    ImGui::SeparatorText("Additional license notices");
    text_muted(
        "Collected vcpkg notices for transitive and build/test-only dependencies. "
        "This list is not a runtime component list."
    );
    if (additional_notices_.empty()) {
        text_muted("No additional license notices are installed in this build.");
    } else if (ImGui::BeginTable(
                   "##notices",
                   2,
                   ImGuiTableFlags_Borders | ImGuiTableFlags_RowBg |
                       ImGuiTableFlags_SizingStretchProp
               )) {
        ImGui::TableSetupColumn("Notice", ImGuiTableColumnFlags_WidthStretch);
        ImGui::TableSetupColumn("Details", ImGuiTableColumnFlags_WidthFixed, 90.0f);
        ImGui::TableHeadersRow();
        for (const auto& file : additional_notices_) {
            const auto name = std::filesystem::path{file}.stem().string();
            ImGui::TableNextRow();
            ImGui::TableNextColumn();
            ImGui::TextUnformatted(name.c_str());
            ImGui::TableNextColumn();
            if (ImGui::SmallButton(("License##" + file).c_str())) {
                (void)open_file(file);
            }
        }
        ImGui::EndTable();
    }

    ImGui::Spacing();
    ImGui::TextWrapped(
        "Full license texts and third-party notices are included in the licenses/ "
        "directory. Redistribution details are in DISTRIBUTION-NOTICE.txt."
    );
    if (std::filesystem::is_regular_file(application_directory() / "DISTRIBUTION-NOTICE.txt")) {
        if (ImGui::SmallButton("Open DISTRIBUTION-NOTICE.txt")) {
            (void)open_file("DISTRIBUTION-NOTICE.txt");
        }
    }
    ImGui::Spacing();
    text_muted("NDI® is a registered trademark of Vizrt NDI AB.");

    ImGui::Unindent(16.0f);
    ImGui::EndChild();
    ImGui::Unindent(16.0f);
    ImGui::Dummy(ImVec2(0.0f, 8.0f));
}

}  // namespace divergencesplitter::ui
