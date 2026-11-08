#include "monitor_row.hpp"

namespace divergencesplitter::ui {

ConditionRowInteraction draw_compact_condition_row(const CompactConditionRow& row,
    bool has_children, int depth, std::string_view role, bool selected,
    const HistoryPlots& history, double now, double seconds,
    const theme::Colors& palette, float scale) {
    ConditionRowInteraction result;
    ImGui::PushID(row.anchor->path.c_str());
    ImGui::TableNextRow(ImGuiTableRowFlags_None, 24 * scale);
    ImGui::TableSetColumnIndex(0);
    const auto pos = ImGui::GetCursorScreenPos();
    const ImVec2 center{pos.x + 7 * scale, pos.y + 10 * scale};
    ImGui::Dummy(ImVec2(14 * scale, 20 * scale));
    auto* draw = ImGui::GetWindowDrawList();
    const auto& status = row.anchor->status;
    const float radius = 3.5f * scale;
    const auto color = ImGui::GetColorU32(status == "true" ? palette.active :
                                        status == "error" ? palette.error : palette.muted);
    if (ImGui::IsItemVisible()) {
        if (status == "true") draw->AddCircleFilled(center, radius, color);
        else if (status == "skipped")
            draw->AddLine(ImVec2(center.x - radius, center.y), ImVec2(center.x + radius, center.y), color, scale);
        else if (status == "error") {
            draw->AddLine(ImVec2(center.x - radius, center.y - radius), ImVec2(center.x + radius, center.y + radius), color, scale);
            draw->AddLine(ImVec2(center.x - radius, center.y + radius), ImVec2(center.x + radius, center.y - radius), color, scale);
        } else draw->AddCircle(center, radius, color, 0, scale);
    }
    if (ImGui::IsItemHovered()) ImGui::SetTooltip("%s", status.c_str());
    if (ImGui::IsItemClicked()) result.selected = row.anchor;

    ImGui::TableSetColumnIndex(1);
    ImGui::Indent(static_cast<float>(depth) * 14 * scale);
    auto label = role.empty() ? row.label : std::string{role} + ": " + row.label;
    auto flags = ImGuiTreeNodeFlags_NoTreePushOnOpen | ImGuiTreeNodeFlags_OpenOnArrow |
                 ImGuiTreeNodeFlags_SpanAvailWidth | ImGuiTreeNodeFlags_FramePadding;
    if (!has_children) flags |= ImGuiTreeNodeFlags_Leaf;
    else if (depth < 2 || (row.branch && row.branch->type == "then")) flags |= ImGuiTreeNodeFlags_DefaultOpen;
    if (selected) flags |= ImGuiTreeNodeFlags_Selected;
    result.open = ImGui::TreeNodeEx("##condition", flags, "%s", label.c_str());
    if (ImGui::IsItemClicked() && !ImGui::IsItemToggledOpen()) result.selected = row.anchor;
    ImGui::Unindent(static_cast<float>(depth) * 14 * scale);

    ImGui::TableSetColumnIndex(2);
    if (row.graph) {
        const ImVec2 size{140 * scale, 22 * scale};
        result.graph_visible = ImGui::IsRectVisible(size);
        if (draw_sparkline("##sparkline", *row.graph, history, now, seconds, size, palette))
            result.selected = row.graph;
    }
    ImGui::PopID();
    return result;
}

} // namespace divergencesplitter::ui
