#pragma once

#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace divergencesplitter::scenario_editor {

class ScenarioEditorError : public std::runtime_error {
public:
    explicit ScenarioEditorError(std::string message) : std::runtime_error(std::move(message)) {}
};

// Editor-facing value tree. It keeps YAML mappings in source order and retains
// aliases as first-class values so that anchors are not expanded while editing.
enum class ValueKind {
    null_value,
    scalar,
    alias,
    sequence,
    mapping,
};

struct Value {
    ValueKind kind{ValueKind::null_value};
    std::string scalar;
    std::vector<Value> sequence;
    std::vector<std::pair<std::string, Value>> mapping;

    [[nodiscard]] static Value make_null();
    [[nodiscard]] static Value make_scalar(std::string value);
    [[nodiscard]] static Value make_alias(std::string anchor);
    [[nodiscard]] static Value make_sequence(std::vector<Value> items = {});
    [[nodiscard]] static Value make_mapping(
        std::vector<std::pair<std::string, Value>> entries = {}
    );

    [[nodiscard]] bool is_null() const noexcept { return kind == ValueKind::null_value; }
    [[nodiscard]] bool is_scalar() const noexcept { return kind == ValueKind::scalar; }
    [[nodiscard]] bool is_alias() const noexcept { return kind == ValueKind::alias; }
    [[nodiscard]] bool is_sequence() const noexcept { return kind == ValueKind::sequence; }
    [[nodiscard]] bool is_mapping() const noexcept { return kind == ValueKind::mapping; }

    [[nodiscard]] const Value* find(std::string_view key) const;
    [[nodiscard]] Value* find(std::string_view key);
    [[nodiscard]] const Value* find_index(std::size_t index) const;
    [[nodiscard]] Value* find_index(std::size_t index);

    // Appends the key or replaces the existing value while retaining its position.
    void set(std::string key, Value value);
    bool erase(std::string_view key);
};

struct ConditionUsage {
    Value value;

    [[nodiscard]] bool is_reference() const noexcept;
    [[nodiscard]] bool is_inheritance() const noexcept;
    [[nodiscard]] std::string anchor() const;
};

enum class DefinitionKind {
    condition,
    detector,
    other,
};

struct SharedDefinition {
    std::string name;
    DefinitionKind kind{DefinitionKind::condition};
    Value value;
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
    std::vector<SharedDefinition> definitions;
    std::optional<ConditionUsage> start_condition;
    std::optional<ConditionUsage> reset_condition;
    std::optional<ConditionUsage> incomplete_condition;
    std::vector<std::optional<SplitDefinition>> splits;
};

[[nodiscard]] DefinitionKind classify_definition(const Value& value);
[[nodiscard]] const SharedDefinition* find_definition(
    const ScenarioDocument& document,
    std::string_view name
);
[[nodiscard]] SharedDefinition* find_definition(ScenarioDocument& document, std::string_view name);

// Collects IDs from the condition hierarchy exactly where `extends` can target
// them, excluding arbitrary mapping fields such as Detector settings.
[[nodiscard]] std::vector<std::string> condition_ids(const Value& value);

// Applies aliases and `extends`/`overrides` using the same rules as the runtime
// loader. Invalid references, duplicate IDs, unknown override IDs, and invalid
// override fields throw ScenarioEditorError.
[[nodiscard]] Value resolve_condition(const ScenarioDocument& document, const Value& value);

// Validates shared-definition uniqueness, alias targets, inheritance rules, and
// cycles. Editor commands use this before committing a change.
void validate_scenario_document(const ScenarioDocument& document);

// Dependency-first shared definition order: a definition that aliases another
// definition follows it in the emitted YAML.
[[nodiscard]] std::vector<const SharedDefinition*> ordered_definitions(
    const ScenarioDocument& document
);

}  // namespace divergencesplitter::scenario_editor
