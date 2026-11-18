#include "editor_detail.hpp"

namespace divergencesplitter::scenario_editor::detail {

Value* traverse(Value* value, const Path& path, std::size_t from) {
    for (std::size_t index = from; index < path.size(); ++index) {
        const auto& token = path[index];
        if (token.is_index) {
            if (!value->is_sequence() || token.index >= value->sequence.size()) {
                throw ScenarioEditorError("edit path index is out of range");
            }
            value = &value->sequence[token.index];
        } else {
            if (!value->is_mapping()) {
                throw ScenarioEditorError("edit path expected a mapping at '" + token.key + "'");
            }
            value = value->find(token.key);
            if (value == nullptr) {
                throw ScenarioEditorError("edit path field was not found: " + token.key);
            }
        }
    }
    return value;
}

bool is_usage_value(const Value& value) {
    return value.is_mapping() && value.find("use") != nullptr;
}

std::string_view definition_kind_name(DefinitionKind kind) {
    return kind == DefinitionKind::condition ? "condition" : "detector";
}

std::optional<DefinitionRef> find_use_definition(
    ScenarioDocument& document,
    const Value& usage,
    DefinitionKind expected
) {
    const auto* use = usage.find("use");
    if (use == nullptr || !use->is_scalar() || use->scalar.empty()) {
        return std::nullopt;
    }
    auto* condition = find_condition_definition(document, use->scalar);
    auto* detector = find_detector_definition(document, use->scalar);
    if (expected == DefinitionKind::condition) {
        if (condition != nullptr) {
            return DefinitionRef{
                DefinitionKind::condition,
                condition->name,
                &condition->condition,
                &condition->parameters,
            };
        }
        if (detector != nullptr) {
            throw ScenarioEditorError(
                "condition use refers to a detector definition: " + use->scalar
            );
        }
    } else {
        if (detector != nullptr) {
            return DefinitionRef{
                DefinitionKind::detector,
                detector->name,
                &detector->detector,
                &detector->parameters,
            };
        }
        if (condition != nullptr) {
            throw ScenarioEditorError(
                "detector use refers to a condition definition: " + use->scalar
            );
        }
    }
    throw ScenarioEditorError(
        std::string(definition_kind_name(expected)) + " definition was not found: "
        + use->scalar
    );
}

DefinitionKind expected_kind_for_key(std::string_view key, DefinitionKind current) {
    if (key == "detector") {
        return DefinitionKind::detector;
    }
    if (key == "condition" || key == "reset_condition" || key == "conditions") {
        return DefinitionKind::condition;
    }
    return current;
}

const Value* value_at_path(const Value& root, const Path& path) {
    const Value* current = &root;
    for (const auto& token : path) {
        if (token.is_index) {
            if (!current->is_sequence() || token.index >= current->sequence.size()) {
                return nullptr;
            }
            current = &current->sequence[token.index];
        } else {
            if (!current->is_mapping()) {
                return nullptr;
            }
            current = current->find(token.key);
            if (current == nullptr) {
                return nullptr;
            }
        }
    }
    return current;
}

}  // namespace divergencesplitter::scenario_editor::detail
