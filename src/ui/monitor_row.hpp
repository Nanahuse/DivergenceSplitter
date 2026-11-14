#pragma once

#include "theme.hpp"
#include "monitor_model.hpp"

namespace divergencesplitter::ui {

struct ConditionRowInteraction {
    bool open{};
    const ConditionDiagnosticsNode* selected{};
};

// One compact row in the current-conditions summary.
ConditionRowInteraction draw_compact_condition_row(const CompactConditionRow& row,
    bool has_children, int depth, std::string_view role, bool selected,
    const theme::Colors& palette, float scale);

} // namespace divergencesplitter::ui
