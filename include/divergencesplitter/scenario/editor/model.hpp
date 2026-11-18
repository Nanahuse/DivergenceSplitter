#pragma once

#include <map>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "divergencesplitter/scenario/v2.hpp"
#include "divergencesplitter/scenario/value.hpp"

namespace divergencesplitter::scenario_editor {

using scenario::Value;
using scenario::ValueKind;

class ScenarioEditorError : public std::runtime_error {
public:
    explicit ScenarioEditorError(std::string message) : std::runtime_error(std::move(message)) {}
};

struct ConditionUsage {
    Value value;

    [[nodiscard]] bool is_shared_use() const noexcept;
    [[nodiscard]] std::string use_name() const;
    [[nodiscard]] const Value* with() const;
};

struct RuleDefinition {
    ConditionUsage condition;
    std::string action;
};

struct ScenarioRule {
    bool sequence{false};
    RuleDefinition rule;
    std::vector<RuleDefinition> sequence_rules;
};

struct SplitDefinition {
    std::vector<ScenarioRule> rules;
};

struct ScenarioDocument {
    scenario::v2::Definitions definitions;
    std::optional<ConditionUsage> start_condition;
    std::optional<ConditionUsage> reset_condition;
    std::optional<ConditionUsage> incomplete_condition;
    std::vector<std::optional<SplitDefinition>> splits;
    std::vector<std::pair<std::string, Value>> extra_root;
};

enum class FieldKind {
    text,
    number,
    integer,
    duration,
    condition,
    condition_list,
    detector,
    roi,
    number_list,
};

struct FieldSchema {
    std::string name;
    FieldKind kind{FieldKind::text};
    bool required{false};
    Value default_value;
};

struct EditorSchema {
    std::map<std::string, std::vector<FieldSchema>> condition_fields;
    std::map<std::string, std::vector<FieldSchema>> detector_fields;
};

[[nodiscard]] const EditorSchema& editor_schema();
void validate_condition_schema(const Value& value);
void validate_detector_schema(const Value& value);

[[nodiscard]] const scenario::v2::SharedCondition* find_condition_definition(
    const ScenarioDocument& document,
    std::string_view name
);
[[nodiscard]] scenario::v2::SharedCondition* find_condition_definition(
    ScenarioDocument& document,
    std::string_view name
);
[[nodiscard]] const scenario::v2::SharedDetector* find_detector_definition(
    const ScenarioDocument& document,
    std::string_view name
);
[[nodiscard]] scenario::v2::SharedDetector* find_detector_definition(
    ScenarioDocument& document,
    std::string_view name
);

[[nodiscard]] Value resolved_condition(
    const ScenarioDocument& document,
    const Value& usage
);
[[nodiscard]] Value resolved_detector(
    const ScenarioDocument& document,
    const Value& usage
);

[[nodiscard]] scenario::v2::Document to_v2_document(const ScenarioDocument& document);
void validate_scenario_document(const ScenarioDocument& document);

}  // namespace divergencesplitter::scenario_editor
