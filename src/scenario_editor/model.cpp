#include "divergencesplitter/scenario/editor/model.hpp"

#include <algorithm>
#include <array>
#include <functional>
#include <map>
#include <set>
#include <string>
#include <utility>

namespace divergencesplitter::scenario_editor {
namespace {

constexpr std::array<std::string_view, 12> condition_types{
    "detected",
    "all",
    "any",
    "not",
    "rising_edge",
    "falling_edge",
    "once",
    "elapsed",
    "hold",
    "nth",
    "reset_when",
    "then",
};

constexpr std::array<std::string_view, 9> detector_types{
    "template_match",
    "mean_absolute_similarity",
    "root_mean_square_similarity",
    "histogram_similarity",
    "perceptual_hash_similarity",
    "difference_hash_similarity",
    "mean_brightness",
    "color_range",
    "phase_correlation",
};

bool forbidden_override_key(std::string_view key) {
    return key == "type" || key == "id" || key == "conditions" || key == "condition"
        || key == "reset_condition" || key == "extends" || key == "overrides";
}

const Value* child_slot(const Value& value, std::string_view key) {
    if (!value.is_mapping()) {
        return nullptr;
    }
    return value.find(key);
}

template <typename Visit>
void for_each_alias(const Value& value, Visit&& visit) {
    if (value.is_alias()) {
        visit(value.scalar);
        return;
    }
    for (const auto& [key, item] : value.mapping) {
        (void)key;
        for_each_alias(item, visit);
    }
    for (const auto& item : value.sequence) {
        for_each_alias(item, visit);
    }
}

void collect_ids(const Value& value, std::set<std::string>& result) {
    if (value.is_alias()) {
        return;
    }
    if (value.is_sequence()) {
        for (const auto& item : value.sequence) {
            collect_ids(item, result);
        }
        return;
    }
    if (!value.is_mapping()) {
        return;
    }
    if (const auto* id = value.find("id"); id != nullptr && id->is_scalar() && !id->scalar.empty()) {
        result.insert(id->scalar);
    }
    for (const auto key : {"condition", "reset_condition"}) {
        if (const auto* nested = child_slot(value, key); nested != nullptr) {
            collect_ids(*nested, result);
        }
    }
    if (const auto* conditions = value.find("conditions"); conditions != nullptr) {
        collect_ids(*conditions, result);
    }
}

std::map<std::string, Value*> index_condition_ids(Value& value) {
    std::map<std::string, Value*> result;
    const auto visit = [&](auto&& self, Value& node) -> void {
        if (node.is_alias()) {
            return;
        }
        if (node.is_sequence()) {
            for (auto& item : node.sequence) {
                self(self, item);
            }
            return;
        }
        if (!node.is_mapping()) {
            return;
        }
        if (const auto* id = node.find("id"); id != nullptr) {
            if (!id->is_scalar() || id->scalar.empty()) {
                throw ScenarioEditorError("condition ids must be non-empty strings");
            }
            if (!result.emplace(id->scalar, &node).second) {
                throw ScenarioEditorError("condition id is duplicated: " + id->scalar);
            }
        }
        for (const auto key : {"condition", "reset_condition"}) {
            if (auto* nested = node.find(key); nested != nullptr) {
                self(self, *nested);
            }
        }
        if (auto* conditions = node.find("conditions"); conditions != nullptr) {
            self(self, *conditions);
        }
    };
    visit(visit, value);
    return result;
}

void merge_patch(Value& target, const Value& patch) {
    if (!target.is_mapping() || !patch.is_mapping()) {
        target = patch;
        return;
    }
    for (const auto& [key, patch_value] : patch.mapping) {
        if (forbidden_override_key(key)) {
            throw ScenarioEditorError("field cannot be overridden: " + key);
        }
        auto* current = target.find(key);
        if (key == "detector") {
            if (!patch_value.is_mapping() || current == nullptr || !current->is_mapping()) {
                throw ScenarioEditorError(
                    "detector overrides must modify an existing Detector mapping"
                );
            }
        }
        if (patch_value.is_null()) {
            target.erase(key);
        } else if (current != nullptr && current->is_mapping() && patch_value.is_mapping()) {
            merge_patch(*current, patch_value);
        } else {
            target.set(key, patch_value);
        }
    }
}

void apply_overrides(Value& base, const Value& overrides) {
    if (!overrides.is_mapping()) {
        throw ScenarioEditorError("overrides must be a mapping of condition IDs");
    }
    auto targets = index_condition_ids(base);
    for (const auto& [id, patch] : overrides.mapping) {
        const auto found = targets.find(id);
        if (found == targets.end()) {
            throw ScenarioEditorError("override condition ID was not found: " + id);
        }
        if (!patch.is_mapping()) {
            throw ScenarioEditorError("an override for condition '" + id + "' must be a mapping");
        }
        merge_patch(*found->second, patch);
    }
}

Value resolve_impl(
    const ScenarioDocument& document,
    const Value& value,
    std::set<std::string>& expanding
) {
    if (value.is_alias()) {
        const auto* definition = find_definition(document, value.scalar);
        if (definition == nullptr) {
            throw ScenarioEditorError("alias target was not found: " + value.scalar);
        }
        if (!expanding.insert(value.scalar).second) {
            throw ScenarioEditorError("cyclic alias or extends reference: " + value.scalar);
        }
        auto resolved = resolve_impl(document, definition->value, expanding);
        expanding.erase(value.scalar);
        return resolved;
    }
    if (value.is_sequence()) {
        Value result = Value::make_sequence();
        result.sequence.reserve(value.sequence.size());
        for (const auto& item : value.sequence) {
            result.sequence.push_back(resolve_impl(document, item, expanding));
        }
        return result;
    }
    if (!value.is_mapping()) {
        return value;
    }

    const auto* extends = value.find("extends");
    if (extends == nullptr) {
        if (value.find("overrides") != nullptr) {
            throw ScenarioEditorError("overrides requires extends");
        }
        if (const auto* id = value.find("id");
            id != nullptr && (!id->is_scalar() || id->scalar.empty())) {
            throw ScenarioEditorError("condition ids must be non-empty strings");
        }
        Value result = Value::make_mapping();
        result.mapping.reserve(value.mapping.size());
        for (const auto& [key, item] : value.mapping) {
            result.mapping.emplace_back(key, resolve_impl(document, item, expanding));
        }
        return result;
    }

    for (const auto& [key, item] : value.mapping) {
        (void)item;
        if (key != "extends" && key != "overrides" && key != "id") {
            throw ScenarioEditorError(
                "extends conditions can only set extends, overrides, and id: " + key
            );
        }
    }
    if (!extends->is_alias()) {
        throw ScenarioEditorError("extends must be a YAML alias to a Condition");
    }
    const auto* local_id = value.find("id");
    if (local_id != nullptr && (!local_id->is_scalar() || local_id->scalar.empty())) {
        throw ScenarioEditorError("condition ids must be non-empty strings");
    }

    const auto inherited = resolve_impl(document, *extends, expanding);
    if (!inherited.is_mapping() || inherited.find("type") == nullptr) {
        throw ScenarioEditorError("extends must refer to a Condition mapping with a type");
    }
    Value result = inherited;
    const auto* overrides = value.find("overrides");
    if (overrides != nullptr) {
        apply_overrides(result, *overrides);
    } else {
        const Value empty = Value::make_mapping();
        apply_overrides(result, empty);
    }
    if (local_id != nullptr) {
        result.set("id", *local_id);
    }
    return resolve_impl(document, result, expanding);
}

std::map<std::string, const SharedDefinition*> definition_index(const ScenarioDocument& document) {
    std::map<std::string, const SharedDefinition*> result;
    for (const auto& definition : document.definitions) {
        if (definition.name.empty()) {
            throw ScenarioEditorError("shared definition names must not be empty");
        }
        if (!result.emplace(definition.name, &definition).second) {
            throw ScenarioEditorError("shared definition is duplicated: " + definition.name);
        }
    }
    return result;
}

}  // namespace

Value Value::make_null() {
    return Value{};
}

Value Value::make_scalar(std::string value) {
    Value result;
    result.kind = ValueKind::scalar;
    result.scalar = std::move(value);
    return result;
}

Value Value::make_alias(std::string anchor) {
    Value result;
    result.kind = ValueKind::alias;
    result.scalar = std::move(anchor);
    return result;
}

Value Value::make_sequence(std::vector<Value> items) {
    Value result;
    result.kind = ValueKind::sequence;
    result.sequence = std::move(items);
    return result;
}

Value Value::make_mapping(std::vector<std::pair<std::string, Value>> entries) {
    Value result;
    result.kind = ValueKind::mapping;
    result.mapping = std::move(entries);
    return result;
}

const Value* Value::find(std::string_view key) const {
    if (!is_mapping()) {
        return nullptr;
    }
    const auto found = std::find_if(mapping.begin(), mapping.end(), [&](const auto& entry) {
        return entry.first == key;
    });
    return found == mapping.end() ? nullptr : &found->second;
}

Value* Value::find(std::string_view key) {
    return const_cast<Value*>(std::as_const(*this).find(key));
}

const Value* Value::find_index(std::size_t index) const {
    if (!is_sequence() || index >= sequence.size()) {
        return nullptr;
    }
    return &sequence[index];
}

Value* Value::find_index(std::size_t index) {
    return const_cast<Value*>(std::as_const(*this).find_index(index));
}

void Value::set(std::string key, Value value) {
    if (!is_mapping()) {
        *this = make_mapping();
    }
    const auto found = std::find_if(mapping.begin(), mapping.end(), [&](const auto& entry) {
        return entry.first == key;
    });
    if (found == mapping.end()) {
        mapping.emplace_back(std::move(key), std::move(value));
    } else {
        found->second = std::move(value);
    }
}

bool Value::erase(std::string_view key) {
    if (!is_mapping()) {
        return false;
    }
    const auto found = std::find_if(mapping.begin(), mapping.end(), [&](const auto& entry) {
        return entry.first == key;
    });
    if (found == mapping.end()) {
        return false;
    }
    mapping.erase(found);
    return true;
}

bool ConditionUsage::is_reference() const noexcept {
    return value.is_alias();
}

bool ConditionUsage::is_inheritance() const noexcept {
    if (!value.is_mapping()) {
        return false;
    }
    const auto* extends = value.find("extends");
    return extends != nullptr && extends->is_alias();
}

std::string ConditionUsage::anchor() const {
    if (is_reference()) {
        return value.scalar;
    }
    if (is_inheritance()) {
        return value.find("extends")->scalar;
    }
    return {};
}

DefinitionKind classify_definition(const Value& value) {
    if (!value.is_mapping()) {
        return DefinitionKind::other;
    }
    if (const auto* type = value.find("type"); type != nullptr && type->is_scalar()) {
        if (std::find(condition_types.begin(), condition_types.end(), type->scalar)
            != condition_types.end()) {
            return DefinitionKind::condition;
        }
        if (std::find(detector_types.begin(), detector_types.end(), type->scalar)
            != detector_types.end()) {
            return DefinitionKind::detector;
        }
        return DefinitionKind::other;
    }
    if (value.find("extends") != nullptr) {
        return DefinitionKind::condition;
    }
    return DefinitionKind::other;
}

const SharedDefinition* find_definition(const ScenarioDocument& document, std::string_view name) {
    const auto found = std::find_if(document.definitions.begin(), document.definitions.end(), [&](const auto& definition) {
        return definition.name == name;
    });
    return found == document.definitions.end() ? nullptr : &*found;
}

SharedDefinition* find_definition(ScenarioDocument& document, std::string_view name) {
    return const_cast<SharedDefinition*>(find_definition(std::as_const(document), name));
}

std::vector<std::string> condition_ids(const Value& value) {
    std::set<std::string> ids;
    collect_ids(value, ids);
    return {ids.begin(), ids.end()};
}

Value resolve_condition(const ScenarioDocument& document, const Value& value) {
    std::set<std::string> expanding;
    return resolve_impl(document, value, expanding);
}

void validate_scenario_document(const ScenarioDocument& document) {
    const auto definitions = definition_index(document);

    for (const auto& definition : document.definitions) {
        if (definition.value.is_alias()) {
            throw ScenarioEditorError(
                "shared definition must have a concrete mapping: " + definition.name
            );
        }
        if (!definition.value.is_mapping()) {
            throw ScenarioEditorError(
                "shared definition must be a mapping: " + definition.name
            );
        }
        for_each_alias(definition.value, [&](const std::string& alias) {
            if (!definitions.contains(alias)) {
                throw ScenarioEditorError("alias target was not found: " + alias);
            }
        });
    }

    const auto check_usage = [&](const ConditionUsage& usage) {
        if (!usage.value.is_mapping() && !usage.value.is_alias()) {
            throw ScenarioEditorError("conditions must be mappings or aliases");
        }
        const auto resolved = resolve_condition(document, usage.value);
        validate_condition_schema(resolved);
    };

    for (const auto& definition : document.definitions) {
        const auto resolved = resolve_condition(document, definition.value);
        switch (classify_definition(resolved)) {
        case DefinitionKind::condition:
            validate_condition_schema(resolved);
            break;
        case DefinitionKind::detector:
            validate_detector_schema(resolved);
            break;
        case DefinitionKind::other:
            break;
        }
    }
    if (document.start_condition) {
        check_usage(*document.start_condition);
    }
    if (document.reset_condition) {
        check_usage(*document.reset_condition);
    }
    if (document.incomplete_condition) {
        check_usage(*document.incomplete_condition);
    }
    for (const auto& split : document.splits) {
        if (!split) {
            continue;
        }
        for (const auto& rule : split->rules) {
            if (rule.sequence) {
                for (const auto& step : rule.sequence_rules) {
                    check_usage(step.condition);
                }
            } else {
                check_usage(rule.rule.condition);
            }
        }
    }

    (void)ordered_definitions(document);
}

std::vector<const SharedDefinition*> ordered_definitions(const ScenarioDocument& document) {
    const auto definitions = definition_index(document);
    std::map<std::string, int> state;
    std::vector<const SharedDefinition*> result;
    result.reserve(document.definitions.size());

    const std::function<void(const SharedDefinition&)> visit = [&](const SharedDefinition& definition) {
        const auto found = state.find(definition.name);
        if (found != state.end()) {
            if (found->second == 1) {
                throw ScenarioEditorError(
                    "cyclic shared definition dependency: " + definition.name
                );
            }
            return;
        }
        state[definition.name] = 1;
        for_each_alias(definition.value, [&](const std::string& alias) {
            const auto dependency = definitions.find(alias);
            if (dependency != definitions.end()) {
                visit(*dependency->second);
            }
        });
        state[definition.name] = 2;
        result.push_back(&definition);
    };

    for (const auto& definition : document.definitions) {
        visit(definition);
    }
    return result;
}

}  // namespace divergencesplitter::scenario_editor
