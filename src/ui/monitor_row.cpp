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
    const float indent = depth > 0 ? static_cast<float>(depth) * 12 * scale +
        (has_children ? 0 : ImGui::GetTreeNodeToLabelSpacing()) : 0;
    if (indent > 0) ImGui::Indent(indent);
    const auto label = role.empty() ? row.label : std::string{role} + ": " + row.label;
    const auto& status = row.anchor->status;
    ImGui::PushStyleColor(ImGuiCol_Text, status == "true" ? palette.active :
        status == "error" ? palette.error : status == "skipped" ? palette.muted : palette.text);
    if (has_children) {
        auto flags = ImGuiTreeNodeFlags_NoTreePushOnOpen | ImGuiTreeNodeFlags_OpenOnArrow |
                     ImGuiTreeNodeFlags_SpanAvailWidth | ImGuiTreeNodeFlags_FramePadding;
        if (depth < 2 || (row.branch && row.branch->type == "then")) flags |= ImGuiTreeNodeFlags_DefaultOpen;
        if (selected) flags |= ImGuiTreeNodeFlags_Selected;
        result.open = ImGui::TreeNodeEx("##condition", flags, "%s", label.c_str());
        if (ImGui::IsItemClicked() && !ImGui::IsItemToggledOpen()) result.selected = row.anchor;
    } else if (ImGui::Selectable((label + "##condition").c_str(), selected,
                                ImGuiSelectableFlags_None, ImVec2(0, 22 * scale)))
        result.selected = row.anchor;
    if (ImGui::IsItemHovered()) ImGui::SetTooltip("%s | %s", label.c_str(), status.c_str());
    ImGui::PopStyleColor();
    if (indent > 0) ImGui::Unindent(indent);

    ImGui::TableSetColumnIndex(1);
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
