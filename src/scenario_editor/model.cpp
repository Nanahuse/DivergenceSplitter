#include "divergencesplitter/scenario/editor/model.hpp"

#include <algorithm>
#include <array>
#include <map>
#include <set>
#include <string>
#include <utility>

namespace divergencesplitter::scenario_editor {
namespace {

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

const Value* child_slot(const Value& value, std::string_view key) {
    if (!value.is_mapping()) {
        return nullptr;
    }
    return value.find(key);
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
        if (auto* id = node.find("id"); id != nullptr && id->is_scalar() && !id->scalar.empty()) {
            result.emplace(id->scalar, &node);
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
        auto* current = target.find(key);
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
        return;
    }
    auto targets = index_condition_ids(base);
    for (const auto& [id, patch] : overrides.mapping) {
        const auto found = targets.find(id);
        if (found == targets.end()) {
            continue;
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
        if (definition == nullptr || definition->kind != DefinitionKind::condition
            || !definition->value.is_mapping() || expanding.contains(value.scalar)) {
            return value;
        }
        expanding.insert(value.scalar);
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

    if (const auto* extends = value.find("extends"); extends != nullptr && extends->is_alias()) {
        const auto inherited = resolve_impl(document, *extends, expanding);
        if (inherited.is_mapping()) {
            Value result = inherited;
            if (const auto* overrides = value.find("overrides"); overrides != nullptr) {
                apply_overrides(result, *overrides);
            }
            return resolve_impl(document, result, expanding);
        }
    }

    Value result = Value::make_mapping();
    result.mapping.reserve(value.mapping.size());
    for (const auto& [key, item] : value.mapping) {
        result.mapping.emplace_back(key, resolve_impl(document, item, expanding));
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
    if (value.is_mapping()) {
        if (const auto* type = value.find("type"); type != nullptr && type->is_scalar()) {
            const auto found = std::find(detector_types.begin(), detector_types.end(), type->scalar);
            if (found != detector_types.end()) {
                return DefinitionKind::detector;
            }
        }
    }
    return DefinitionKind::condition;
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

}  // namespace divergencesplitter::scenario_editor
