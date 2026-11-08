#pragma once

#include "history_plot.hpp"
#include "monitor_model.hpp"

namespace divergencesplitter::ui {

struct ConditionRowInteraction {
    bool open{};
    bool graph_visible{};
    const ConditionDiagnosticsNode* selected{};
};

// Call inside the Monitor's name/graph table. One projected Condition = one row.
ConditionRowInteraction draw_compact_condition_row(const CompactConditionRow& row,
    bool has_children, int depth, std::string_view role, bool selected,
    const HistoryPlots& history, double now, double seconds,
    const theme::Colors& palette, float scale);

} // namespace divergencesplitter::ui
