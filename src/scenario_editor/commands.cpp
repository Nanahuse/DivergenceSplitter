#include "divergencesplitter/scenario/editor/document.hpp"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <locale>
#include <sstream>
#include <functional>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

namespace divergencesplitter::scenario_editor {
namespace {

constexpr std::size_t max_undo_steps = 256;

struct PathToken {
    bool is_index{false};
    std::size_t index{};
    std::string key;
};

using Path = std::vector<PathToken>;

Path parse_path(const nlohmann::json& command) {
    const auto found = command.find("path");
    if (found == command.end() || !found->is_array()) {
        throw ScenarioEditorError("command.path must be an array");
    }
    Path path;
    for (const auto& token : *found) {
        if (token.is_number_integer() && token.get<std::int64_t>() >= 0) {
            path.push_back(PathToken{
                true, static_cast<std::size_t>(token.get<std::int64_t>()), {}
            });
        } else if (token.is_string()) {
            path.push_back(PathToken{false, 0, token.get<std::string>()});
        } else {
            throw ScenarioEditorError("command.path entries must be strings or indexes");
        }
    }
    if (path.empty()) {
        throw ScenarioEditorError("command.path must not be empty");
    }
    return path;
}

const PathToken& require_key(const Path& path, std::size_t index, std::string_view command) {
    if (index >= path.size() || path[index].is_index) {
        throw ScenarioEditorError(std::string(command) + " path is incomplete");
    }
    return path[index];
}

const PathToken& require_index(const Path& path, std::size_t index, std::string_view command) {
    if (index >= path.size() || !path[index].is_index) {
        throw ScenarioEditorError(std::string(command) + " path requires an index");
    }
    return path[index];
}

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

Value* resolve_path(ScenarioDocument& document, const Path& path) {
    const auto& first = require_key(path, 0, "edit");
    if (first.key == "definitions") {
        const auto& name = require_key(path, 1, "edit");
        auto* definition = find_definition(document, name.key);
        if (definition == nullptr) {
            throw ScenarioEditorError("shared definition was not found: " + name.key);
        }
        return traverse(&definition->value, path, 2);
    }
    if (first.key == "start_condition" || first.key == "reset_condition"
        || first.key == "incomplete_condition") {
        std::optional<ConditionUsage>* slot = nullptr;
        if (first.key == "start_condition") {
            slot = &document.start_condition;
        } else if (first.key == "reset_condition") {
            slot = &document.reset_condition;
        } else {
            slot = &document.incomplete_condition;
        }
        if (!slot->has_value()) {
            throw ScenarioEditorError(first.key + " is not configured");
        }
        ConditionUsage& usage = slot->value();
        return traverse(&usage.value, path, 1);
    }
    if (first.key == "splits") {
        const auto split_index = require_index(path, 1, "splits").index;
        if (split_index >= document.splits.size() || !document.splits[split_index]) {
            throw ScenarioEditorError("split was not found or is manual");
        }
        auto& split = *document.splits[split_index];
        if (require_key(path, 2, "splits").key != "rules") {
            throw ScenarioEditorError("only split rules can be edited");
        }
        const auto rule_index = require_index(path, 3, "splits").index;
        if (rule_index >= split.rules.size()) {
            throw ScenarioEditorError("rule index is out of range");
        }
        auto& rule = split.rules[rule_index];
        if (require_key(path, 4, "splits").key != "condition") {
            throw ScenarioEditorError("only rule conditions can be edited");
        }
        if (rule.sequence) {
            throw ScenarioEditorError("sequence rules must address a condition step");
        }
        return traverse(&rule.rule.condition.value, path, 5);
    }
    throw ScenarioEditorError("unknown edit path root: " + first.key);
}

Value* resolve_condition_container(ScenarioDocument& document, const Path& path) {
    Value* value = resolve_path(document, path);
    if (value->is_alias() || (value->is_mapping() && value->find("extends") != nullptr)) {
        throw ScenarioEditorError("children of a referenced shared condition cannot be edited");
    }
    return value;
}

void replace_aliases(Value& value, std::string_view from, std::string_view to) {
    if (value.is_alias()) {
        if (value.scalar == from) {
            value.scalar = std::string{to};
        }
        return;
    }
    for (auto& [key, item] : value.mapping) {
        (void)key;
        replace_aliases(item, from, to);
    }
    for (auto& item : value.sequence) {
        replace_aliases(item, from, to);
    }
}

void materialize_definition_refs(
    Value& value,
    std::string_view name,
    const ScenarioDocument& document,
    const Value& replacement
) {
    if (value.is_alias()) {
        if (value.scalar == name) {
            value = replacement;
        }
        return;
    }
    if (value.is_mapping()) {
        const auto* extends = value.find("extends");
        if (extends != nullptr && extends->is_alias() && extends->scalar == name) {
            value = resolve_condition(document, value);
            return;
        }
    }
    for (auto& [key, item] : value.mapping) {
        (void)key;
        materialize_definition_refs(item, name, document, replacement);
    }
    for (auto& item : value.sequence) {
        materialize_definition_refs(item, name, document, replacement);
    }
}

bool forbidden_override_key(std::string_view key) {
    return key == "type" || key == "id" || key == "conditions" || key == "condition"
        || key == "reset_condition" || key == "extends" || key == "overrides";
}

void set_nested_override(Value& overrides, const std::string& condition_id, const nlohmann::json& command) {
    if (!overrides.is_mapping()) {
        overrides = Value::make_mapping();
    }
    Value* patch = overrides.find(condition_id);
    if (patch == nullptr) {
        overrides.set(condition_id, Value::make_mapping());
        patch = overrides.find(condition_id);
    }
    if (!patch->is_mapping()) {
        *patch = Value::make_mapping();
    }

    const auto setting_path = command.find("setting_path");
    if (setting_path == command.end() || setting_path->empty()) {
        if (setting_path != command.end() && !setting_path->is_array()) {
            throw ScenarioEditorError("setting_path must be an array");
        }
        const auto value = command.find("value");
        if (value == command.end()) {
            throw ScenarioEditorError("set_override requires value");
        }
        if (!value->is_object()) {
            throw ScenarioEditorError("a condition override must be a mapping");
        }
        for (const auto& [key, item] : value->items()) {
            (void)item;
            if (forbidden_override_key(key)) {
                throw ScenarioEditorError("field cannot be overridden: " + key);
            }
        }
        *patch = value_from_json(*value);
        return;
    }
    if (!setting_path->is_array()) {
        throw ScenarioEditorError("setting_path must be an array");
    }

    Value* target = patch;
    for (std::size_t index = 0; index + 1 < setting_path->size(); ++index) {
        const auto& token = (*setting_path)[index];
        if (!token.is_string()) {
            throw ScenarioEditorError("override setting paths must use string keys");
        }
        const std::string key = token.get<std::string>();
        if (forbidden_override_key(key)) {
            throw ScenarioEditorError("field cannot be overridden: " + key);
        }
        Value* next = target->find(key);
        if (next == nullptr) {
            target->set(key, Value::make_mapping());
            next = target->find(key);
        }
        if (!next->is_mapping()) {
            *next = Value::make_mapping();
        }
        target = next;
    }
    const auto& final_token = setting_path->back();
    if (!final_token.is_string()) {
        throw ScenarioEditorError("override setting paths must end with a key");
    }
    const std::string final_key = final_token.get<std::string>();
    if (forbidden_override_key(final_key)) {
        throw ScenarioEditorError("field cannot be overridden: " + final_key);
    }
    const auto value = command.find("value");
    if (value == command.end()) {
        throw ScenarioEditorError("set_override requires value");
    }
    target->set(final_key, value_from_json(*value));
}

void remove_nested_override(Value& overrides, const std::string& condition_id, const nlohmann::json& command) {
    if (!overrides.is_mapping()) {
        return;
    }
    Value* patch = overrides.find(condition_id);
    if (patch == nullptr) {
        return;
    }
    const auto setting_path = command.find("setting_path");
    if (setting_path == command.end() || setting_path->empty()) {
        overrides.erase(condition_id);
        return;
    }
    if (!setting_path->is_array()) {
        throw ScenarioEditorError("setting_path must be an array");
    }
    Value* target = patch;
    for (std::size_t index = 0; index + 1 < setting_path->size(); ++index) {
        const auto& token = (*setting_path)[index];
        if (!token.is_string()) {
            throw ScenarioEditorError("override setting paths must use string keys");
        }
        target = target->find(token.get<std::string>());
        if (target == nullptr) {
            return;
        }
    }
    if (!setting_path->back().is_string()) {
        throw ScenarioEditorError("override setting paths must end with a key");
    }
    target->erase(setting_path->back().get<std::string>());
}

RuleDefinition default_rule() {
    RuleDefinition rule;
    rule.condition.value = Value::make_mapping({
        {"type", Value::make_scalar("elapsed")},
        {"duration", Value::make_scalar("1s")},
    });
    rule.action = "split";
    return rule;
}

bool yaml_ambiguous_string(std::string_view text) {
    if (text.empty()) {
        return true;
    }
    std::string lowered{text};
    std::transform(lowered.begin(), lowered.end(), lowered.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    static const std::set<std::string> ambiguous{
        "~", "null", "true", "false", "yes", "no", "on", "off",
        ".nan", ".inf", "-.inf", "+.inf",
    };
    if (ambiguous.contains(lowered)) {
        return true;
    }
    std::istringstream stream{std::string{text}};
    stream.imbue(std::locale::classic());
    stream.unsetf(std::ios::dec);
    double number{};
    if ((stream >> std::noskipws >> number) && (stream >> std::ws).eof()) {
        return true;
    }
    return false;
}

std::string field_kind_name(FieldKind kind) {
    switch (kind) {
    case FieldKind::text:
        return "text";
    case FieldKind::number:
        return "number";
    case FieldKind::integer:
        return "integer";
    case FieldKind::duration:
        return "duration";
    case FieldKind::condition:
        return "condition";
    case FieldKind::condition_list:
        return "condition_list";
    case FieldKind::detector:
        return "detector";
    case FieldKind::roi:
        return "roi";
    case FieldKind::number_list:
        return "number_list";
    }
    return "text";
}

const std::vector<FieldSchema>& condition_fields_or_throw(const std::string& type) {
    const auto found = editor_schema().condition_fields.find(type);
    if (found == editor_schema().condition_fields.end()) {
        throw ScenarioEditorError("unsupported condition type: " + type);
    }
    return found->second;
}

const std::vector<FieldSchema>& detector_fields_or_throw(const std::string& type) {
    const auto found = editor_schema().detector_fields.find(type);
    if (found == editor_schema().detector_fields.end()) {
        throw ScenarioEditorError("unsupported detector type: " + type);
    }
    return found->second;
}

Value build_typed_mapping(
    const std::string& type,
    const std::vector<FieldSchema>& fields,
    const Value* old_value,
    bool preserve_id
) {
    Value result = Value::make_mapping();
    result.set("type", Value::make_scalar(type));
    if (preserve_id && old_value != nullptr && old_value->is_mapping()) {
        if (const auto* id = old_value->find("id"); id != nullptr) {
            result.set("id", *id);
        }
    }
    for (const auto& field : fields) {
        const auto* previous = old_value != nullptr && old_value->is_mapping()
            ? old_value->find(field.name)
            : nullptr;
        if (previous != nullptr) {
            result.set(field.name, *previous);
        } else if (field.required) {
            result.set(field.name, field.default_value);
        }
    }
    return result;
}

nlohmann::json schema_fields_json(const std::map<std::string, std::vector<FieldSchema>>& fields) {
    nlohmann::json result = nlohmann::json::object();
    for (const auto& [type, definitions] : fields) {
        nlohmann::json items = nlohmann::json::array();
        for (const auto& definition : definitions) {
            items.push_back(nlohmann::json{
                {"name", definition.name},
                {"kind", field_kind_name(definition.kind)},
                {"required", definition.required},
                {"default", value_to_json(definition.default_value)},
            });
        }
        result[type] = std::move(items);
    }
    return result;
}

nlohmann::json editor_schema_json() {
    return nlohmann::json{
        {"conditionFields", schema_fields_json(editor_schema().condition_fields)},
        {"detectorFields", schema_fields_json(editor_schema().detector_fields)},
    };
}

void mutate_document(ScenarioDocument& document, const nlohmann::json& command) {
    const std::string type = command.at("type").get<std::string>();
    if (type == "set_value") {
        *resolve_path(document, parse_path(command)) = value_from_json(command.at("value"));
        return;
    }
    if (type == "set_setting") {
        Value* target = resolve_path(document, parse_path(command));
        if (!target->is_mapping()) {
            throw ScenarioEditorError("set_setting target must be a mapping");
        }
        const std::string key = command.at("key").get<std::string>();
        if (key == "extends" || key == "overrides") {
            throw ScenarioEditorError("use set_usage to change shared condition references");
        }
        target->set(key, value_from_json(command.at("value")));
        return;
    }
    if (type == "set_condition_type") {
        Value* target = resolve_path(document, parse_path(command));
        if (!target->is_mapping() || target->find("extends") != nullptr) {
            throw ScenarioEditorError(
                "condition type can only be changed on an inline condition"
            );
        }
        const std::string next_type = command.at("value").get<std::string>();
        const auto& fields = condition_fields_or_throw(next_type);
        *target = build_typed_mapping(next_type, fields, target, true);
        return;
    }
    if (type == "set_detector_type") {
        Value* target = resolve_path(document, parse_path(command));
        if (!target->is_mapping() || target->find("type") == nullptr) {
            throw ScenarioEditorError("detector type can only be changed on a detector mapping");
        }
        const std::string next_type = command.at("value").get<std::string>();
        const auto& fields = detector_fields_or_throw(next_type);
        *target = build_typed_mapping(next_type, fields, target, false);
        return;
    }
    if (type == "remove_setting") {
        Value* target = resolve_path(document, parse_path(command));
        if (!target->is_mapping()) {
            throw ScenarioEditorError("remove_setting target must be a mapping");
        }
        target->erase(command.at("key").get<std::string>());
        return;
    }
    if (type == "add_condition" || type == "insert_condition") {
        Value* target = resolve_condition_container(document, parse_path(command));
        Value* conditions = target->find("conditions");
        if (conditions == nullptr) {
            target->set("conditions", Value::make_sequence());
            conditions = target->find("conditions");
        }
        if (!conditions->is_sequence()) {
            throw ScenarioEditorError("conditions must be a sequence");
        }
        const std::size_t index = command.contains("index")
            ? command.at("index").get<std::size_t>()
            : conditions->sequence.size();
        if (index > conditions->sequence.size()) {
            throw ScenarioEditorError("condition index is out of range");
        }
        Value value = command.contains("value")
            ? value_from_json(command.at("value"))
            : default_rule().condition.value;
        conditions->sequence.insert(conditions->sequence.begin() + static_cast<std::ptrdiff_t>(index), std::move(value));
        return;
    }
    if (type == "remove_condition") {
        Value* target = resolve_condition_container(document, parse_path(command));
        Value* conditions = target->find("conditions");
        if (conditions == nullptr || !conditions->is_sequence()) {
            throw ScenarioEditorError("conditions must be a sequence");
        }
        const std::size_t index = command.at("index").get<std::size_t>();
        if (index >= conditions->sequence.size()) {
            throw ScenarioEditorError("condition index is out of range");
        }
        conditions->sequence.erase(conditions->sequence.begin() + static_cast<std::ptrdiff_t>(index));
        return;
    }
    if (type == "move_condition") {
        Value* target = resolve_condition_container(document, parse_path(command));
        Value* conditions = target->find("conditions");
        if (conditions == nullptr || !conditions->is_sequence()) {
            throw ScenarioEditorError("conditions must be a sequence");
        }
        const std::size_t from = command.at("from").get<std::size_t>();
        const std::size_t to = command.at("to").get<std::size_t>();
        if (from >= conditions->sequence.size() || to >= conditions->sequence.size()) {
            throw ScenarioEditorError("condition move index is out of range");
        }
        if (from == to) {
            return;
        }
        Value moved = std::move(conditions->sequence[from]);
        conditions->sequence.erase(conditions->sequence.begin() + static_cast<std::ptrdiff_t>(from));
        conditions->sequence.insert(conditions->sequence.begin() + static_cast<std::ptrdiff_t>(to), std::move(moved));
        return;
    }
    if (type == "set_usage") {
        Value* target = resolve_path(document, parse_path(command));
        const std::string mode = command.at("mode").get<std::string>();
        if (mode == "reference") {
            const std::string anchor = command.at("anchor").get<std::string>();
            if (anchor.empty()) {
                throw ScenarioEditorError("a shared condition reference requires an anchor");
            }
            *target = Value::make_alias(anchor);
            return;
        }
        if (mode == "inherits") {
            const std::string anchor = command.at("anchor").get<std::string>();
            if (anchor.empty()) {
                throw ScenarioEditorError("a shared condition inheritance requires an anchor");
            }
            Value replacement = Value::make_mapping();
            replacement.set("extends", Value::make_alias(anchor));
            if (target->is_mapping()) {
                const auto* extends = target->find("extends");
                const auto* overrides = target->find("overrides");
                if (extends != nullptr && extends->is_alias() && extends->scalar == anchor
                    && overrides != nullptr) {
                    replacement.set("overrides", *overrides);
                }
            }
            *target = std::move(replacement);
            return;
        }
        if (mode == "inline") {
            if (command.contains("value")) {
                *target = value_from_json(command.at("value"));
            } else {
                *target = resolve_condition(document, *target);
                if (target->is_alias()) {
                    throw ScenarioEditorError("the shared condition could not be resolved");
                }
            }
            return;
        }
        throw ScenarioEditorError("unknown condition usage mode: " + mode);
    }
    if (type == "set_definition") {
        const std::string name = command.at("name").get<std::string>();
        if (name.empty()) {
            throw ScenarioEditorError("shared definition names must not be empty");
        }
        Value value = value_from_json(command.at("value"));
        if (!value.is_mapping()) {
            throw ScenarioEditorError("shared definitions must be mappings");
        }
        auto* definition = find_definition(document, name);
        if (definition == nullptr) {
            document.definitions.push_back(SharedDefinition{
                name, classify_definition(value), std::move(value)
            });
        } else {
            definition->kind = classify_definition(value);
            definition->value = std::move(value);
        }
        return;
    }
    if (type == "rename_definition") {
        const std::string from = command.at("from").get<std::string>();
        const std::string to = command.at("to").get<std::string>();
        if (to.empty()) {
            throw ScenarioEditorError("shared definition names must not be empty");
        }
        auto* definition = find_definition(document, from);
        if (definition == nullptr) {
            throw ScenarioEditorError("shared definition was not found: " + from);
        }
        if (find_definition(document, to) != nullptr) {
            throw ScenarioEditorError("shared definition already exists: " + to);
        }
        definition->name = to;
        for (auto& other : document.definitions) {
            replace_aliases(other.value, from, to);
        }
        const auto replace_usage = [&](std::optional<ConditionUsage>& usage) {
            if (usage) {
                replace_aliases(usage->value, from, to);
            }
        };
        replace_usage(document.start_condition);
        replace_usage(document.reset_condition);
        replace_usage(document.incomplete_condition);
        for (auto& split : document.splits) {
            if (!split) {
                continue;
            }
            for (auto& rule : split->rules) {
                if (rule.sequence) {
                    for (auto& step : rule.sequence_rules) {
                        replace_aliases(step.condition.value, from, to);
                    }
                } else {
                    replace_aliases(rule.rule.condition.value, from, to);
                }
            }
        }
        return;
    }
    if (type == "delete_definition") {
        const std::string name = command.at("name").get<std::string>();
        const auto found = std::find_if(document.definitions.begin(), document.definitions.end(), [&](const auto& definition) {
            return definition.name == name;
        });
        if (found == document.definitions.end()) {
            throw ScenarioEditorError("shared definition was not found: " + name);
        }
        const Value replacement = found->value;
        for (auto& definition : document.definitions) {
            if (definition.name != name) {
                materialize_definition_refs(definition.value, name, document, replacement);
            }
        }
        const auto materialize_usage = [&](std::optional<ConditionUsage>& usage) {
            if (usage) {
                materialize_definition_refs(usage->value, name, document, replacement);
            }
        };
        materialize_usage(document.start_condition);
        materialize_usage(document.reset_condition);
        materialize_usage(document.incomplete_condition);
        for (auto& split : document.splits) {
            if (!split) {
                continue;
            }
            for (auto& rule : split->rules) {
                if (rule.sequence) {
                    for (auto& step : rule.sequence_rules) {
                        materialize_definition_refs(step.condition.value, name, document, replacement);
                    }
                } else {
                    materialize_definition_refs(rule.rule.condition.value, name, document, replacement);
                }
            }
        }
        document.definitions.erase(found);
        return;
    }
    if (type == "set_optional_condition") {
        const std::string name = command.at("name").get<std::string>();
        std::optional<ConditionUsage>* slot = nullptr;
        if (name == "start_condition") {
            slot = &document.start_condition;
        } else if (name == "reset_condition") {
            slot = &document.reset_condition;
        } else if (name == "incomplete_condition") {
            slot = &document.incomplete_condition;
        } else {
            throw ScenarioEditorError("unknown optional condition: " + name);
        }
        if (!command.at("enabled").get<bool>()) {
            slot->reset();
            return;
        }
        Value fallback = Value::make_mapping({
            {"type", Value::make_scalar("elapsed")},
            {"duration", Value::make_scalar("1s")},
        });
        Value value = command.contains("value") ? value_from_json(command.at("value")) : fallback;
        if (!value.is_mapping() && !value.is_alias()) {
            throw ScenarioEditorError("a Condition must be a mapping or alias");
        }
        if (!slot->has_value() || command.value("replace", false)) {
            *slot = ConditionUsage{std::move(value)};
        }
        return;
    }
    if (type == "add_split") {
        const std::size_t index = command.contains("index")
            ? command.at("index").get<std::size_t>()
            : document.splits.size();
        if (index > document.splits.size()) {
            throw ScenarioEditorError("split index is out of range");
        }
        document.splits.insert(
            document.splits.begin() + static_cast<std::ptrdiff_t>(index),
            command.value("manual", false) ? std::optional<SplitDefinition>{} : std::optional<SplitDefinition>{SplitDefinition{}}
        );
        return;
    }
    if (type == "remove_split") {
        const std::size_t index = command.at("index").get<std::size_t>();
        if (index >= document.splits.size()) {
            throw ScenarioEditorError("split index is out of range");
        }
        document.splits.erase(document.splits.begin() + static_cast<std::ptrdiff_t>(index));
        return;
    }
    if (type == "move_split") {
        const std::size_t from = command.at("from").get<std::size_t>();
        const std::size_t to = command.at("to").get<std::size_t>();
        if (from >= document.splits.size() || to >= document.splits.size()) {
            throw ScenarioEditorError("split move index is out of range");
        }
        if (from == to) {
            return;
        }
        auto moved = std::move(document.splits[from]);
        document.splits.erase(document.splits.begin() + static_cast<std::ptrdiff_t>(from));
        document.splits.insert(document.splits.begin() + static_cast<std::ptrdiff_t>(to), std::move(moved));
        return;
    }
    if (type == "set_split_manual") {
        const std::size_t index = command.at("index").get<std::size_t>();
        if (index >= document.splits.size()) {
            throw ScenarioEditorError("split index is out of range");
        }
        if (command.at("manual").get<bool>()) {
            document.splits[index] = std::nullopt;
        } else if (!document.splits[index]) {
            document.splits[index] = SplitDefinition{};
        }
        return;
    }
    if (type == "add_rule") {
        const std::size_t split_index = command.at("split").get<std::size_t>();
        if (split_index >= document.splits.size() || !document.splits[split_index]) {
            throw ScenarioEditorError("split was not found or is manual");
        }
        auto& rules = document.splits[split_index]->rules;
        const std::size_t index = command.contains("index")
            ? command.at("index").get<std::size_t>()
            : rules.size();
        if (index > rules.size()) {
            throw ScenarioEditorError("rule index is out of range");
        }
        ScenarioRule rule;
        if (command.value("sequence", false)) {
            rule.sequence = true;
            rule.sequence_rules.push_back(default_rule());
        } else {
            rule.rule = default_rule();
        }
        rules.insert(rules.begin() + static_cast<std::ptrdiff_t>(index), std::move(rule));
        return;
    }
    if (type == "remove_rule") {
        const std::size_t split_index = command.at("split").get<std::size_t>();
        if (split_index >= document.splits.size() || !document.splits[split_index]) {
            throw ScenarioEditorError("split was not found or is manual");
        }
        auto& rules = document.splits[split_index]->rules;
        const std::size_t index = command.at("index").get<std::size_t>();
        if (index >= rules.size()) {
            throw ScenarioEditorError("rule index is out of range");
        }
        rules.erase(rules.begin() + static_cast<std::ptrdiff_t>(index));
        return;
    }
    if (type == "move_rule") {
        const std::size_t split_index = command.at("split").get<std::size_t>();
        if (split_index >= document.splits.size() || !document.splits[split_index]) {
            throw ScenarioEditorError("split was not found or is manual");
        }
        auto& rules = document.splits[split_index]->rules;
        const std::size_t from = command.at("from").get<std::size_t>();
        const std::size_t to = command.at("to").get<std::size_t>();
        if (from >= rules.size() || to >= rules.size()) {
            throw ScenarioEditorError("rule move index is out of range");
        }
        if (from == to) {
            return;
        }
        ScenarioRule moved = std::move(rules[from]);
        rules.erase(rules.begin() + static_cast<std::ptrdiff_t>(from));
        rules.insert(rules.begin() + static_cast<std::ptrdiff_t>(to), std::move(moved));
        return;
    }
    if (type == "set_action") {
        const std::size_t split_index = command.at("split").get<std::size_t>();
        if (split_index >= document.splits.size() || !document.splits[split_index]) {
            throw ScenarioEditorError("split was not found or is manual");
        }
        auto& rules = document.splits[split_index]->rules;
        const std::size_t index = command.at("index").get<std::size_t>();
        if (index >= rules.size()) {
            throw ScenarioEditorError("rule index is out of range");
        }
        const std::string action = command.at("action").get<std::string>();
        if (rules[index].sequence) {
            const std::size_t step = command.contains("step")
                ? command.at("step").get<std::size_t>()
                : 0;
            if (step >= rules[index].sequence_rules.size()) {
                throw ScenarioEditorError("sequence step is out of range");
            }
            rules[index].sequence_rules[step].action = action;
        } else {
            rules[index].rule.action = action;
        }
        return;
    }
    if (type == "set_override" || type == "add_override") {
        Value* target = resolve_path(document, parse_path(command));
        if (!target->is_mapping()) {
            throw ScenarioEditorError("condition overrides require a condition mapping");
        }
        const auto* extends = target->find("extends");
        if (extends == nullptr || !extends->is_alias()) {
            throw ScenarioEditorError("condition overrides require an extends reference");
        }
        Value* overrides = target->find("overrides");
        if (overrides == nullptr) {
            target->set("overrides", Value::make_mapping());
            overrides = target->find("overrides");
        }
        const std::string condition_id = command.at("condition_id").get<std::string>();
        if (condition_id.empty()) {
            throw ScenarioEditorError("override condition_id must not be empty");
        }
        if (const auto* definition = find_definition(document, extends->scalar)) {
            const auto inherited = resolve_condition(document, definition->value);
            const auto ids = condition_ids(inherited);
            if (std::find(ids.begin(), ids.end(), condition_id) == ids.end()) {
                throw ScenarioEditorError(
                    "override condition ID was not found in the inherited definition: "
                    + condition_id
                );
            }
        }
        set_nested_override(*overrides, condition_id, command);
        return;
    }
    if (type == "remove_override") {
        Value* target = resolve_path(document, parse_path(command));
        Value* overrides = target->is_mapping() ? target->find("overrides") : nullptr;
        if (overrides == nullptr) {
            return;
        }
        const std::string condition_id = command.at("condition_id").get<std::string>();
        remove_nested_override(*overrides, condition_id, command);
        return;
    }
    throw ScenarioEditorError("unknown editor command: " + type);
}

nlohmann::json rule_json(const ScenarioDocument& document, const RuleDefinition& rule) {
    return nlohmann::json{
        {"condition", value_to_json(rule.condition.value)},
        {"condition_resolved", value_to_json(resolve_condition(document, rule.condition.value))},
        {"action", rule.action},
    };
}

nlohmann::json scenario_rule_json(const ScenarioDocument& document, const ScenarioRule& rule) {
    if (rule.sequence) {
        nlohmann::json steps = nlohmann::json::array();
        for (const auto& step : rule.sequence_rules) {
            steps.push_back(rule_json(document, step));
        }
        return nlohmann::json{{"sequence", std::move(steps)}};
    }
    return rule_json(document, rule.rule);
}

nlohmann::json resolved_usage_json(
    const ScenarioDocument& document,
    const std::optional<ConditionUsage>& usage
) {
    if (!usage) {
        return nullptr;
    }
    return value_to_json(resolve_condition(document, usage->value));
}

}  // namespace

nlohmann::json value_to_json(const Value& value) {
    switch (value.kind) {
    case ValueKind::null_value:
        return nullptr;
    case ValueKind::scalar:
        return value.scalar;
    case ValueKind::alias:
        return nlohmann::json{{"$alias", value.scalar}};
    case ValueKind::sequence: {
        nlohmann::json result = nlohmann::json::array();
        for (const auto& item : value.sequence) {
            result.push_back(value_to_json(item));
        }
        return result;
    }
    case ValueKind::mapping: {
        nlohmann::json result = nlohmann::json::object();
        for (const auto& [key, item] : value.mapping) {
            result[key] = value_to_json(item);
        }
        return result;
    }
    }
    return nullptr;
}

Value value_from_json(const nlohmann::json& value) {
    if (value.is_null()) {
        return Value::make_null();
    }
    if (value.is_string()) {
        Value result = Value::make_scalar(value.get<std::string>());
        result.quoted = yaml_ambiguous_string(result.scalar);
        return result;
    }
    if (value.is_boolean()) {
        return Value::make_scalar(value.get<bool>() ? "true" : "false");
    }
    if (value.is_number()) {
        return Value::make_scalar(value.dump());
    }
    if (value.is_array()) {
        Value result = Value::make_sequence();
        result.sequence.reserve(value.size());
        for (const auto& item : value) {
            result.sequence.push_back(value_from_json(item));
        }
        return result;
    }
    if (value.is_object()) {
        if (value.size() == 1 && value.contains("$alias") && value["$alias"].is_string()) {
            return Value::make_alias(value["$alias"].get<std::string>());
        }
        Value result = Value::make_mapping();
        for (const auto& [key, item] : value.items()) {
            result.mapping.emplace_back(key, value_from_json(item));
        }
        return result;
    }
    throw ScenarioEditorError("unsupported JSON value");
}

EditorSession new_editor_session() {
    EditorSession session;
    session.document.start_condition = ConditionUsage{
        Value::make_mapping({
            {"type", Value::make_scalar("elapsed")},
            {"duration", Value::make_scalar("2s")},
        })
    };
    return session;
}

EditorSession open_editor_session(const std::filesystem::path& path) {
    EditorSession session;
    session.document = load_scenario_document(path);
    session.path = path;
    return session;
}

void apply_editor_command(EditorSession& session, const nlohmann::json& command) {
    if (!command.is_object() || !command.contains("type") || !command["type"].is_string()) {
        throw ScenarioEditorError("editor command must have a type");
    }
    const std::string type = command["type"].get<std::string>();
    if (type == "undo") {
        undo_editor(session);
        return;
    }
    if (type == "redo") {
        redo_editor(session);
        return;
    }
    ScenarioDocument next = session.document;
    mutate_document(next, command);
    validate_scenario_document(next);
    if (session.undo_stack.size() >= max_undo_steps) {
        session.undo_stack.erase(session.undo_stack.begin());
    }
    session.undo_stack.push_back(std::move(session.document));
    session.document = std::move(next);
    session.redo_stack.clear();
    session.dirty = true;
}

void undo_editor(EditorSession& session) {
    if (session.undo_stack.empty()) {
        throw ScenarioEditorError("nothing to undo");
    }
    session.redo_stack.push_back(std::move(session.document));
    session.document = std::move(session.undo_stack.back());
    session.undo_stack.pop_back();
    session.dirty = true;
}

void redo_editor(EditorSession& session) {
    if (session.redo_stack.empty()) {
        throw ScenarioEditorError("nothing to redo");
    }
    session.undo_stack.push_back(std::move(session.document));
    session.document = std::move(session.redo_stack.back());
    session.redo_stack.pop_back();
    session.dirty = true;
}

void save_editor_session(EditorSession& session, const std::filesystem::path& path) {
    save_scenario_document(session.document, path);
    session.path = path;
    session.dirty = false;
}

nlohmann::json editor_state_json(const EditorSession& session) {
    nlohmann::json definitions = nlohmann::json::array();
    for (const auto& definition : session.document.definitions) {
        const auto resolved = resolve_condition(session.document, definition.value);
        const char* kind = "other";
        if (definition.kind == DefinitionKind::condition) {
            kind = "condition";
        } else if (definition.kind == DefinitionKind::detector) {
            kind = "detector";
        }
        definitions.push_back(nlohmann::json{
            {"name", definition.name},
            {"kind", kind},
            {"value", value_to_json(definition.value)},
            {"resolved", value_to_json(resolved)},
            {"ids", condition_ids(resolved)},
        });
    }
    nlohmann::json splits = nlohmann::json::array();
    for (const auto& split : session.document.splits) {
        if (!split) {
            splits.push_back(nullptr);
            continue;
        }
        nlohmann::json rules = nlohmann::json::array();
        for (const auto& rule : split->rules) {
            rules.push_back(scenario_rule_json(session.document, rule));
        }
        splits.push_back(nlohmann::json{{"rules", std::move(rules)}});
    }

    nlohmann::json extra_root = nlohmann::json::object();
    for (const auto& [key, value] : session.document.extra_root) {
        extra_root[key] = value_to_json(value);
    }

    nlohmann::json document = nlohmann::json{
        {"path", path_to_utf8(session.path)},
        {"dirty", session.dirty},
        {"extra_root", std::move(extra_root)},
        {"definitions", std::move(definitions)},
        {"start_condition", session.document.start_condition
                ? value_to_json(session.document.start_condition->value)
                : nlohmann::json(nullptr)},
        {"start_condition_resolved", resolved_usage_json(
                session.document, session.document.start_condition)},
        {"reset_condition", session.document.reset_condition
                ? value_to_json(session.document.reset_condition->value)
                : nlohmann::json(nullptr)},
        {"reset_condition_resolved", resolved_usage_json(
                session.document, session.document.reset_condition)},
        {"incomplete_condition", session.document.incomplete_condition
                ? value_to_json(session.document.incomplete_condition->value)
                : nlohmann::json(nullptr)},
        {"incomplete_condition_resolved", resolved_usage_json(
                session.document, session.document.incomplete_condition)},
        {"splits", std::move(splits)},
    };
    return nlohmann::json{
        {"version", 2},
        {"schema", editor_schema_json()},
        {"document", std::move(document)},
        {"canUndo", !session.undo_stack.empty()},
        {"canRedo", !session.redo_stack.empty()},
    };
}

}  // namespace divergencesplitter::scenario_editor
