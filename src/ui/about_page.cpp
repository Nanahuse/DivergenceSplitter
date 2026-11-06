#include "about_page.hpp"

#include <imgui.h>

#include "divergencesplitter/capture/ndi.hpp"
#include "ui_helpers.hpp"

namespace divergencesplitter::ui {

AboutPage::AboutPage() = default;

void AboutPage::draw() {
    ImGui::Dummy(ImVec2(0.0f, 8.0f));
    ImGui::Indent(16.0f);
    ImGui::TextUnformatted("DivergenceSplitter");
    text_muted("Version " DIVERGENCESPLITTER_VERSION);
    ImGui::Spacing();

    ImGui::TextLinkOpenURL("GitHub", "https://github.com/Nanahuse/DivergenceSplitter");
    ImGui::SameLine();
    ImGui::TextUnformatted("|");
    ImGui::SameLine();
    ImGui::TextLinkOpenURL("NDI website", "https://ndi.video/");
    text_muted("NDI® is a registered trademark of Vizrt NDI AB.");

    ImGui::Spacing();
    ImGui::Separator();
    ImGui::Spacing();

    ImGui::BeginChild("##about_scroll", ImVec2(0.0f, 0.0f), false);
    ImGui::Indent(16.0f);
    ImGui::SeparatorText("Components");
    ImGui::BulletText("Dear ImGui interface");
    ImGui::BulletText("Win32 window and Direct3D 11 rendering");
    ImGui::BulletText("OpenCV image processing");
    ImGui::BulletText("livesplit-bridge-client-cpp (LiveSplit.Bridge JSON protocol)");
    ImGui::BulletText("rapidyaml (ryml) scenario loading");

    ImGui::Spacing();
    ImGui::SeparatorText("NDI®");
    ImGui::TextWrapped("%s", ndi_runtime_status().message.c_str());
    ImGui::TextWrapped(
        "The NDI runtime is not bundled with DivergenceSplitter. Install NDI Runtime "
        "separately to use NDI input; restart the application after installation. "
        "NDI® is a registered trademark of Vizrt NDI AB. The runtime is separately "
        "licensed by NDI, Inc. / Vizrt NDI AB. See the official NDI SDK License "
        "Agreement at https://ndi.link/ndisdk_license."
    );

    ImGui::Spacing();
    ImGui::SeparatorText("License");
    ImGui::TextWrapped(
        "DivergenceSplitter is distributed under the MIT License. Third-party license "
        "notices are included in the distribution under licenses/ and "
        "DISTRIBUTION-NOTICE.txt."
    );
    ImGui::Unindent(16.0f);
    ImGui::EndChild();
    ImGui::Unindent(16.0f);
    ImGui::Dummy(ImVec2(0.0f, 8.0f));
}

}  // namespace divergencesplitter::ui
