#include "divergencesplitter/scenario/editor/document.hpp"

#include "editor_detail.hpp"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace divergencesplitter::scenario_editor {
namespace {

using detail::DefinitionKind;
using detail::DefinitionRef;
using detail::Path;
using detail::PathToken;
using detail::definition_kind_name;
using detail::expected_kind_for_key;
using detail::find_use_definition;
using detail::is_usage_value;
using detail::traverse;
using detail::value_at_path;

Path setting_path_from_json(const nlohmann::json& command);
void erase_usage_with(Value& usage, const std::string& parameter);

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

Value* resolve_path(ScenarioDocument& document, const Path& path) {
    const auto& first = require_key(path, 0, "edit");
    if (first.key == "definitions") {
        const auto& section = require_key(path, 1, "edit");
        const auto& name = require_key(path, 2, "edit");
        if (section.key == "conditions") {
            auto* definition = find_condition_definition(document, name.key);
            if (definition == nullptr) {
                throw ScenarioEditorError("condition definition was not found: " + name.key);
            }
            if (path.size() == 3) {
                return &definition->condition;
            }
            if (!path[3].is_index && path[3].key == "parameters") {
                const auto& parameter_name = require_key(path, 4, "edit");
                const auto found = std::find_if(
                    definition->parameters.begin(),
                    definition->parameters.end(),
                    [&](const auto& parameter) { return parameter.name == parameter_name.key; }
                );
                if (found == definition->parameters.end()) {
                    throw ScenarioEditorError(
                        "parameter definition was not found: " + parameter_name.key
                    );
                }
                return &found->default_value;
            }
            return traverse(&definition->condition, path, 3);
        }
        if (section.key == "detectors") {
            auto* definition = find_detector_definition(document, name.key);
            if (definition == nullptr) {
                throw ScenarioEditorError("detector definition was not found: " + name.key);
            }
            if (path.size() == 3) {
                return &definition->detector;
            }
            if (!path[3].is_index && path[3].key == "parameters") {
                const auto& parameter_name = require_key(path, 4, "edit");
                const auto found = std::find_if(
                    definition->parameters.begin(),
                    definition->parameters.end(),
                    [&](const auto& parameter) { return parameter.name == parameter_name.key; }
                );
                if (found == definition->parameters.end()) {
                    throw ScenarioEditorError(
                        "parameter definition was not found: " + parameter_name.key
                    );
                }
                return &found->default_value;
            }
            return traverse(&definition->detector, path, 3);
        }
        throw ScenarioEditorError("definitions path must use conditions or detectors");
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
        const auto& condition_segment = require_key(path, 4, "splits");
        if (rule.sequence) {
            if (condition_segment.key != "sequence") {
                throw ScenarioEditorError("sequence rules must address a condition step");
            }
            const auto step_index = require_index(path, 5, "splits").index;
            if (step_index >= rule.sequence_rules.size()) {
                throw ScenarioEditorError("sequence step is out of range");
            }
            if (require_key(path, 6, "splits").key != "condition") {
                throw ScenarioEditorError("only sequence step conditions can be edited");
            }
            return traverse(&rule.sequence_rules[step_index].condition.value, path, 7);
        }
        if (condition_segment.key != "condition") {
            throw ScenarioEditorError("only rule conditions can be edited");
        }
        return traverse(&rule.rule.condition.value, path, 5);
    }
    throw ScenarioEditorError("unknown edit path root: " + first.key);
}

Value* resolve_inline_container(ScenarioDocument& document, const Path& path) {
    Value* value = resolve_path(document, path);
    if (value->is_mapping() && value->find("use") != nullptr) {
        throw ScenarioEditorError("shared definition usages cannot change their structure");
    }
    return value;
}

void visit_condition_usages(Value& value, const std::function<void(Value&)>& visit) {
    if (is_usage_value(value)) {
        visit(value);
        return;
    }
    if (value.is_sequence()) {
        for (auto& item : value.sequence) {
            visit_condition_usages(item, visit);
        }
        return;
    }
    if (!value.is_mapping()) {
        return;
    }
    for (const auto key : {"condition", "reset_condition"}) {
        if (auto* child = value.find(key); child != nullptr) {
            visit_condition_usages(*child, visit);
        }
    }
    if (auto* conditions = value.find("conditions"); conditions != nullptr) {
        visit_condition_usages(*conditions, visit);
    }
}

void visit_scenario_conditions(
    ScenarioDocument& document,
    const std::function<void(Value&)>& visit
) {
    if (document.start_condition) {
        visit_condition_usages(document.start_condition->value, visit);
    }
    if (document.reset_condition) {
        visit_condition_usages(document.reset_condition->value, visit);
    }
    if (document.incomplete_condition) {
        visit_condition_usages(document.incomplete_condition->value, visit);
    }
    for (auto& split : document.splits) {
        if (!split) {
            continue;
        }
        for (auto& rule : split->rules) {
            if (rule.sequence) {
                for (auto& step : rule.sequence_rules) {
                    visit_condition_usages(step.condition.value, visit);
                }
            } else {
                visit_condition_usages(rule.rule.condition.value, visit);
            }
        }
    }
}

void visit_all_conditions(
    ScenarioDocument& document,
    const std::function<void(Value&)>& visit
) {
    for (auto& definition : document.definitions.conditions) {
        visit_condition_usages(definition.condition, visit);
    }
    visit_scenario_conditions(document, visit);
}

void visit_detector_usages(Value& condition, const std::function<void(Value&)>& visit) {
    if (condition.is_sequence()) {
        for (auto& item : condition.sequence) {
            visit_detector_usages(item, visit);
        }
        return;
    }
    if (!condition.is_mapping() || is_usage_value(condition)) {
        return;
    }
    if (auto* detector = condition.find("detector"); detector != nullptr) {
        if (is_usage_value(*detector)) {
            visit(*detector);
        }
    }
    for (const auto key : {"condition", "reset_condition"}) {
        if (auto* child = condition.find(key); child != nullptr) {
            visit_detector_usages(*child, visit);
        }
    }
    if (auto* conditions = condition.find("conditions"); conditions != nullptr) {
        visit_detector_usages(*conditions, visit);
    }
}

void visit_all_detector_usages(
    ScenarioDocument& document,
    const std::function<void(Value&)>& visit
) {
    for (auto& definition : document.definitions.conditions) {
        visit_detector_usages(definition.condition, visit);
    }
    for (auto& definition : document.definitions.detectors) {
        if (is_usage_value(definition.detector)) {
            visit(definition.detector);
        }
    }
    if (document.start_condition) {
        visit_detector_usages(document.start_condition->value, visit);
    }
    if (document.reset_condition) {
        visit_detector_usages(document.reset_condition->value, visit);
    }
    if (document.incomplete_condition) {
        visit_detector_usages(document.incomplete_condition->value, visit);
    }
    for (auto& split : document.splits) {
        if (!split) {
            continue;
        }
        for (auto& rule : split->rules) {
            if (rule.sequence) {
                for (auto& step : rule.sequence_rules) {
                    visit_detector_usages(step.condition.value, visit);
                }
            } else {
                visit_detector_usages(rule.rule.condition.value, visit);
            }
        }
    }
}

std::size_t count_condition_uses(ScenarioDocument& document, std::string_view name) {
    std::size_t count = 0;
    visit_all_conditions(document, [&](Value& value) {
        const auto* use = value.find("use");
        if (use != nullptr && use->is_scalar() && use->scalar == name) {
            ++count;
        }
    });
    return count;
}

std::size_t count_detector_uses(ScenarioDocument& document, std::string_view name) {
    std::size_t count = 0;
    visit_all_detector_usages(document, [&](Value& value) {
        const auto* use = value.find("use");
        if (use != nullptr && use->is_scalar() && use->scalar == name) {
            ++count;
        }
    });
    return count;
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
    const Value* old_value
) {
    Value result = Value::make_mapping();
    result.set("type", Value::make_scalar(type));
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

std::string unique_parameter_name(
    const std::string& definition_name,
    const Path& setting_path,
    const std::vector<scenario::v2::ParameterDefinition>& parameters
) {
    std::string base = definition_name;
    for (const auto& token : setting_path) {
        base += "_";
        if (token.is_index) {
            base += std::to_string(token.index);
        } else {
            base += token.key;
        }
    }
    std::string sanitized;
    sanitized.reserve(base.size());
    for (const unsigned char character : base) {
        if (std::isalnum(character) || character == '_') {
            sanitized.push_back(static_cast<char>(character));
        } else {
            sanitized.push_back('_');
        }
    }
    if (sanitized.empty() || std::isdigit(static_cast<unsigned char>(sanitized.front()))) {
        sanitized.insert(sanitized.begin(), 'p');
    }
    std::string candidate = sanitized;
    std::size_t suffix = 2;
    const auto exists = [&](const std::string& name) {
        return std::any_of(parameters.begin(), parameters.end(), [&](const auto& parameter) {
            return parameter.name == name;
        });
    };
    while (exists(candidate)) {
        candidate = sanitized + "_" + std::to_string(suffix++);
    }
    return candidate;
}

DefinitionKind definition_kind_from_command(const nlohmann::json& command) {
    const std::string kind = command.at("kind").get<std::string>();
    if (kind == "condition") {
        return DefinitionKind::condition;
    }
    if (kind == "detector") {
        return DefinitionKind::detector;
    }
    throw ScenarioEditorError("kind must be condition or detector");
}

DefinitionRef require_definition(
    ScenarioDocument& document,
    DefinitionKind kind,
    const std::string& name
) {
    if (kind == DefinitionKind::condition) {
        auto* definition = find_condition_definition(document, name);
        if (definition == nullptr) {
            throw ScenarioEditorError("condition definition was not found: " + name);
        }
        return DefinitionRef{kind, definition->name, &definition->condition, &definition->parameters};
    }
    auto* definition = find_detector_definition(document, name);
    if (definition == nullptr) {
        throw ScenarioEditorError("detector definition was not found: " + name);
    }
    return DefinitionRef{kind, definition->name, &definition->detector, &definition->parameters};
}

scenario::v2::ParameterDefinition* find_mutable_parameter(
    DefinitionRef definition,
    std::string_view name
) {
    const auto found = std::find_if(
        definition.parameters->begin(),
        definition.parameters->end(),
        [&](const auto& parameter) { return parameter.name == name; }
    );
    return found == definition.parameters->end() ? nullptr : &*found;
}

const scenario::v2::ParameterDefinition* find_parameter(
    const DefinitionRef& definition,
    std::string_view name
) {
    const auto found = std::find_if(
        definition.parameters->begin(),
        definition.parameters->end(),
        [&](const auto& parameter) { return parameter.name == name; }
    );
    return found == definition.parameters->end() ? nullptr : &*found;
}

struct UseStep {
    DefinitionRef parent;
    DefinitionRef child;
    Value* use{};
};

struct LocatedSetting {
    DefinitionRef owner;
    Value* parent{};
    std::string key;
    Value* field{};
    std::vector<UseStep> chain;
};

LocatedSetting locate_setting(
    ScenarioDocument& document,
    DefinitionRef requested,
    const Path& setting_path
) {
    if (setting_path.empty()) {
        throw ScenarioEditorError("setting_path must not be empty");
    }
    DefinitionRef owner = requested;
    Value* current = owner.root;
    DefinitionKind expected = owner.kind;
    std::vector<UseStep> chain;
    std::size_t index = 0;
    while (true) {
        if (is_usage_value(*current)) {
            auto child = find_use_definition(document, *current, expected);
            if (!child) {
                throw ScenarioEditorError("shared definition use is missing a name");
            }
            chain.push_back(UseStep{owner, *child, current});
            owner = *child;
            current = owner.root;
            expected = owner.kind;
            continue;
        }
        const auto& token = setting_path[index];
        if (index + 1 == setting_path.size()) {
            if (token.is_index) {
                throw ScenarioEditorError("setting_path must end with a string key");
            }
            if (!current->is_mapping()) {
                throw ScenarioEditorError("setting path parent must be a mapping");
            }
            return LocatedSetting{
                owner,
                current,
                token.key,
                current->find(token.key),
                std::move(chain),
            };
        }
        if (token.is_index) {
            if (!current->is_sequence() || token.index >= current->sequence.size()) {
                throw ScenarioEditorError("setting path index is out of range");
            }
            current = &current->sequence[token.index];
        } else {
            if (!current->is_mapping()) {
                throw ScenarioEditorError("setting path expected a mapping");
            }
            current = current->find(token.key);
            if (current == nullptr) {
                throw ScenarioEditorError("setting path field was not found: " + token.key);
            }
            expected = expected_kind_for_key(token.key, expected);
        }
        ++index;
    }
}

std::optional<std::string> exposed_parameter_at(
    ScenarioDocument& document,
    DefinitionRef requested,
    const Path& setting_path
) {
    LocatedSetting located = locate_setting(document, requested, setting_path);
    if (located.field == nullptr || !located.field->is_parameter_reference()) {
        return std::nullopt;
    }
    std::string parameter = located.field->scalar;
    if (find_parameter(located.owner, parameter) == nullptr) {
        throw ScenarioEditorError(
            "parameter definition was not found: " + parameter
        );
    }
    for (auto step = located.chain.rbegin(); step != located.chain.rend(); ++step) {
        const auto* with = step->use->find("with");
        if (with == nullptr || !with->is_mapping()) {
            return std::nullopt;
        }
        const auto* forwarded = with->find(parameter);
        if (forwarded == nullptr || !forwarded->is_parameter_reference()) {
            return std::nullopt;
        }
        if (find_parameter(step->parent, forwarded->scalar) == nullptr) {
            throw ScenarioEditorError(
                "parameter definition was not found: " + forwarded->scalar
            );
        }
        parameter = forwarded->scalar;
    }
    return parameter;
}

Value effective_setting_value(
    const ScenarioDocument& document,
    DefinitionRef requested,
    const Path& setting_path,
    const Value& fallback
) {
    Value usage = Value::make_mapping({{"use", Value::make_scalar(requested.name)}});
    const Value resolved = requested.kind == DefinitionKind::condition
        ? scenario::v2::resolve_condition(document.definitions, usage)
        : scenario::v2::resolve_detector(document.definitions, usage);
    const Value* value = value_at_path(resolved, setting_path);
    return value == nullptr ? fallback : *value;
}

Value* ensure_usage_with(Value& usage) {
    Value* with = usage.find("with");
    if (with == nullptr) {
        usage.set("with", Value::make_mapping());
        with = usage.find("with");
    }
    if (!with->is_mapping()) {
        throw ScenarioEditorError("usage.with must be a mapping");
    }
    return with;
}

std::string add_parameter(
    DefinitionRef definition,
    const Path& setting_path,
    const Value& default_value
) {
    const std::string parameter = unique_parameter_name(
        definition.name, setting_path, *definition.parameters
    );
    definition.parameters->push_back(scenario::v2::ParameterDefinition{
        parameter,
        default_value,
    });
    return parameter;
}

void expose_parameter(ScenarioDocument& document, const nlohmann::json& command) {
    const DefinitionKind kind = definition_kind_from_command(command);
    const std::string name = command.at("name").get<std::string>();
    const Path setting_path = setting_path_from_json(command);
    const DefinitionRef requested = require_definition(document, kind, name);

    LocatedSetting located = locate_setting(document, requested, setting_path);
    if (located.field == nullptr) {
        throw ScenarioEditorError("setting field was not found");
    }
    if (is_usage_value(*located.field)) {
        throw ScenarioEditorError("shared definition references cannot be parameters");
    }
    if (exposed_parameter_at(document, requested, setting_path).has_value()) {
        return;
    }

    const Value fallback = located.field->is_parameter_reference()
        ? find_parameter(located.owner, located.field->scalar)->default_value
        : *located.field;
    const Value effective = effective_setting_value(
        document,
        requested,
        setting_path,
        fallback
    );

    if (located.chain.empty()) {
        const std::string parameter = add_parameter(requested, setting_path, effective);
        located.parent->set(located.key, Value::make_parameter_reference(parameter));
        return;
    }

    if (!located.field->is_parameter_reference()) {
        throw ScenarioEditorError(
            "a nested definition setting can only be exposed when the nested definition "
            "already exposes it"
        );
    }
    std::string child_parameter = located.field->scalar;
    if (find_parameter(located.owner, child_parameter) == nullptr) {
        throw ScenarioEditorError(
            "parameter definition was not found: " + child_parameter
        );
    }

    for (auto step = located.chain.rbegin(); step != located.chain.rend(); ++step) {
        Value* with = ensure_usage_with(*step->use);
        Value* forwarded = with->find(child_parameter);
        if (forwarded != nullptr && forwarded->is_parameter_reference()) {
            if (find_parameter(step->parent, forwarded->scalar) == nullptr) {
                throw ScenarioEditorError(
                    "parameter definition was not found: " + forwarded->scalar
                );
            }
            child_parameter = forwarded->scalar;
            continue;
        }
        const std::string parameter = add_parameter(step->parent, setting_path, effective);
        with->set(child_parameter, Value::make_parameter_reference(parameter));
        child_parameter = parameter;
    }
}

void replace_parameter_references(
    Value& value,
    std::string_view parameter,
    const Value& replacement
) {
    if (value.is_parameter_reference() && value.scalar == parameter) {
        value = replacement;
        return;
    }
    for (auto& item : value.sequence) {
        replace_parameter_references(item, parameter, replacement);
    }
    for (auto& [key, item] : value.mapping) {
        (void)key;
        replace_parameter_references(item, parameter, replacement);
    }
}

void unexpose_parameter(ScenarioDocument& document, const nlohmann::json& command) {
    const DefinitionKind kind = definition_kind_from_command(command);
    const std::string name = command.at("name").get<std::string>();
    const Path setting_path = setting_path_from_json(command);
    const DefinitionRef requested = require_definition(document, kind, name);

    const auto exposed = exposed_parameter_at(document, requested, setting_path);
    if (!exposed) {
        return;
    }
    auto* parameter = find_mutable_parameter(requested, *exposed);
    if (parameter == nullptr) {
        throw ScenarioEditorError("parameter definition was not found: " + *exposed);
    }

    const auto inspect = [&](Value& usage) {
        const auto* use = usage.find("use");
        if (use == nullptr || !use->is_scalar() || use->scalar != name) {
            return;
        }
        const auto* with = usage.find("with");
        if (with == nullptr || !with->is_mapping()) {
            return;
        }
        const auto* forwarded = with->find(*exposed);
        if (forwarded != nullptr && forwarded->is_parameter_reference()) {
            throw ScenarioEditorError(
                "parameter is exposed by a parent definition; unexpose it there first"
            );
        }
    };
    if (kind == DefinitionKind::condition) {
        visit_all_conditions(document, inspect);
    } else {
        visit_all_detector_usages(document, inspect);
    }

    const Value default_value = parameter->default_value;
    replace_parameter_references(*requested.root, *exposed, default_value);
    const auto clear = [&](Value& usage) {
        const auto* use = usage.find("use");
        if (use != nullptr && use->is_scalar() && use->scalar == name) {
            erase_usage_with(usage, *exposed);
        }
    };
    if (kind == DefinitionKind::condition) {
        visit_all_conditions(document, clear);
    } else {
        visit_all_detector_usages(document, clear);
    }
    requested.parameters->erase(
        std::remove_if(
            requested.parameters->begin(),
            requested.parameters->end(),
            [&](const auto& item) { return item.name == *exposed; }
        ),
        requested.parameters->end()
    );
}

Path setting_path_from_json(const nlohmann::json& command) {
    const auto found = command.find("setting_path");
    if (found == command.end() || !found->is_array()) {
        throw ScenarioEditorError("setting_path must be an array");
    }
    Path path;
    for (const auto& token : *found) {
        if (token.is_number_integer() && token.get<std::int64_t>() >= 0) {
            path.push_back(PathToken{true, static_cast<std::size_t>(token.get<std::int64_t>()), {}});
        } else if (token.is_string()) {
            path.push_back(PathToken{false, 0, token.get<std::string>()});
        } else {
            throw ScenarioEditorError("setting_path entries must be strings or indexes");
        }
    }
    if (path.empty()) {
        throw ScenarioEditorError("setting_path must not be empty");
    }
    return path;
}

void set_usage_with(Value& usage, const std::string& parameter, const Value& value) {
    Value* with = usage.find("with");
    if (with == nullptr) {
        usage.set("with", Value::make_mapping());
        with = usage.find("with");
    }
    if (!with->is_mapping()) {
        throw ScenarioEditorError("usage.with must be a mapping");
    }
    with->set(parameter, value);
}

void erase_usage_with(Value& usage, const std::string& parameter) {
    auto* with = usage.find("with");
    if (with == nullptr || !with->is_mapping()) {
        return;
    }
    with->erase(parameter);
    if (with->mapping.empty()) {
        usage.erase("with");
    }
}

DefinitionRef require_usage_definition(
    ScenarioDocument& document,
    Value& usage,
    DefinitionKind kind
) {
    if (!is_usage_value(usage)) {
        throw ScenarioEditorError(
            std::string("this command requires a shared ")
            + std::string(definition_kind_name(kind)) + " usage"
        );
    }
    const auto* use = usage.find("use");
    if (use == nullptr || !use->is_scalar()) {
        throw ScenarioEditorError("shared definition use must have a name");
    }
    return require_definition(document, kind, use->scalar);
}

std::string require_exposed_parameter(
    ScenarioDocument& document,
    DefinitionRef definition,
    const Path& setting_path
) {
    const auto exposed = exposed_parameter_at(document, definition, setting_path);
    if (!exposed) {
        throw ScenarioEditorError(
            "setting is not exposed by the shared definition: "
            + definition.name
        );
    }
    return *exposed;
}

void set_usage_setting(
    ScenarioDocument& document,
    Value& usage,
    DefinitionKind kind,
    const Path& setting_path,
    const Value& value
) {
    const DefinitionRef definition = require_usage_definition(document, usage, kind);
    const std::string parameter = require_exposed_parameter(
        document, definition, setting_path
    );
    set_usage_with(usage, parameter, value);
}

void reset_usage_setting(
    ScenarioDocument& document,
    Value& usage,
    DefinitionKind kind,
    const Path& setting_path
) {
    const DefinitionRef definition = require_usage_definition(document, usage, kind);
    const std::string parameter = require_exposed_parameter(
        document, definition, setting_path
    );
    erase_usage_with(usage, parameter);
}

void set_definition_setting(
    ScenarioDocument& document,
    const nlohmann::json& command
) {
    const DefinitionKind kind = definition_kind_from_command(command);
    const std::string name = command.at("name").get<std::string>();
    const Path setting_path = setting_path_from_json(command);
    const Value value = value_from_json(command.at("value"));
    const DefinitionRef requested = require_definition(document, kind, name);

    const auto exposed = exposed_parameter_at(document, requested, setting_path);
    if (exposed) {
        auto* parameter = find_mutable_parameter(requested, *exposed);
        if (parameter == nullptr) {
            throw ScenarioEditorError("parameter definition was not found: " + *exposed);
        }
        parameter->default_value = value;
        return;
    }

    LocatedSetting located = locate_setting(document, requested, setting_path);
    if (!located.chain.empty()) {
        throw ScenarioEditorError(
            "nested definition settings can only be changed when exposed by the "
            "outer definition"
        );
    }
    if (located.field != nullptr) {
        *located.field = value;
    } else {
        located.parent->set(located.key, value);
    }
}

void substitute_with_values(
    Value& value,
    const std::map<std::string, Value>& bindings
) {
    if (value.is_parameter_reference()) {
        const auto found = bindings.find(value.scalar);
        if (found == bindings.end()) {
            throw ScenarioEditorError("parameter definition was not found: " + value.scalar);
        }
        value = found->second;
        return;
    }
    for (auto& item : value.sequence) {
        substitute_with_values(item, bindings);
    }
    for (auto& [key, item] : value.mapping) {
        (void)key;
        substitute_with_values(item, bindings);
    }
}

void substitute_condition_parameters(
    Value& value,
    const std::map<std::string, Value>& bindings
) {
    if (value.is_parameter_reference()) {
        const auto found = bindings.find(value.scalar);
        if (found == bindings.end()) {
            throw ScenarioEditorError("parameter definition was not found: " + value.scalar);
        }
        value = found->second;
        return;
    }
    if (value.is_sequence()) {
        for (auto& item : value.sequence) {
            substitute_condition_parameters(item, bindings);
        }
        return;
    }
    if (!value.is_mapping()) {
        return;
    }
    auto& mapping = value.mapping;
    for (auto item = mapping.begin(); item != mapping.end();) {
        if (item->first == "with") {
            substitute_with_values(item->second, bindings);
            ++item;
            continue;
        }
        if (item->second.is_parameter_reference()) {
            const auto found = bindings.find(item->second.scalar);
            if (found == bindings.end()) {
                throw ScenarioEditorError(
                    "parameter definition was not found: " + item->second.scalar
                );
            }
            if (found->second.is_null()) {
                item = mapping.erase(item);
                continue;
            }
            item->second = found->second;
            ++item;
            continue;
        }
        substitute_condition_parameters(item->second, bindings);
        ++item;
    }
}

Value instantiate_condition_once(
    ScenarioDocument& document,
    const Value& usage
) {
    const auto* use = usage.find("use");
    if (use == nullptr || !use->is_scalar()) {
        throw ScenarioEditorError("shared condition use is missing a name");
    }
    auto* definition = find_condition_definition(document, use->scalar);
    if (definition == nullptr) {
        if (find_detector_definition(document, use->scalar) != nullptr) {
            throw ScenarioEditorError(
                "condition use refers to a detector definition: " + use->scalar
            );
        }
        throw ScenarioEditorError("condition definition was not found: " + use->scalar);
    }

    std::map<std::string, Value> bindings;
    for (const auto& parameter : definition->parameters) {
        bindings[parameter.name] = parameter.default_value;
    }
    if (const auto* with = usage.find("with"); with != nullptr) {
        if (!with->is_mapping()) {
            throw ScenarioEditorError("usage.with must be a mapping");
        }
        for (const auto& [name, value] : with->mapping) {
            if (!bindings.contains(name)) {
                throw ScenarioEditorError(
                    "usage.with contains an unknown parameter: " + name
                );
            }
            bindings[name] = value;
        }
    }

    Value result = definition->condition;
    substitute_condition_parameters(result, bindings);
    return result;
}

bool contains_parameter_reference(const Value& value) {
    if (value.is_parameter_reference()) {
        return true;
    }
    for (const auto& item : value.sequence) {
        if (contains_parameter_reference(item)) {
            return true;
        }
    }
    for (const auto& [key, item] : value.mapping) {
        (void)key;
        if (contains_parameter_reference(item)) {
            return true;
        }
    }
    return false;
}

void extract_condition_definition(
    ScenarioDocument& document,
    const nlohmann::json& command
) {
    const Path path = parse_path(command);
    const std::string name = command.at("name").get<std::string>();
    if (name.empty()) {
        throw ScenarioEditorError("condition definition names must not be empty");
    }
    if (find_condition_definition(document, name) != nullptr) {
        throw ScenarioEditorError("condition definition already exists: " + name);
    }
    if (path.size() == 3 && !path[0].is_index && path[0].key == "definitions"
        && !path[1].is_index && path[1].key == "conditions") {
        throw ScenarioEditorError("a condition definition itself cannot be extracted");
    }
    Value* target = resolve_path(document, path);
    if (is_usage_value(*target)) {
        throw ScenarioEditorError("shared definition usages cannot be extracted");
    }
    if (!target->is_mapping() || target->find("type") == nullptr) {
        throw ScenarioEditorError("only inline conditions can be extracted");
    }
    if (contains_parameter_reference(*target)) {
        throw ScenarioEditorError(
            "conditions that reference parent parameters cannot be extracted"
        );
    }

    Value condition = *target;
    *target = Value::make_mapping({{"use", Value::make_scalar(name)}});
    document.definitions.conditions.push_back(
        scenario::v2::SharedCondition{name, {}, std::move(condition)}
    );
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

}  // namespace

void detail::mutate_document(ScenarioDocument& document, const nlohmann::json& command) {
    const std::string type = command.at("type").get<std::string>();
    if (type == "set_value") {
        const Path edit_path = parse_path(command);
        Value value = value_from_json(command.at("value"));
        try {
            *resolve_path(document, edit_path) = std::move(value);
            return;
        } catch (const ScenarioEditorError&) {
            if (edit_path.back().is_index || edit_path.size() < 2) {
                throw;
            }
            Path parent_path = edit_path;
            parent_path.pop_back();
            Value* parent = resolve_path(document, parent_path);
            if (!parent->is_mapping()) {
                throw ScenarioEditorError("set_value parent must be a mapping");
            }
            parent->set(edit_path.back().key, std::move(value));
            return;
        }
    }
    if (type == "set_setting") {
        Value* target = resolve_path(document, parse_path(command));
        if (!target->is_mapping()) {
            throw ScenarioEditorError("set_setting target must be a mapping");
        }
        const std::string key = command.at("key").get<std::string>();
        if (key == "use" || key == "with") {
            throw ScenarioEditorError("use use_condition/use_detector to change shared references");
        }
        target->set(key, value_from_json(command.at("value")));
        return;
    }
    if (type == "set_condition_type") {
        Value* target = resolve_inline_container(document, parse_path(command));
        if (!target->is_mapping()) {
            throw ScenarioEditorError("condition type can only be changed on a condition mapping");
        }
        const std::string next_type = command.at("value").get<std::string>();
        const auto& fields = condition_fields_or_throw(next_type);
        *target = build_typed_mapping(next_type, fields, target);
        return;
    }
    if (type == "set_detector_type") {
        Value* target = resolve_inline_container(document, parse_path(command));
        if (!target->is_mapping() || target->find("type") == nullptr) {
            throw ScenarioEditorError("detector type can only be changed on a detector mapping");
        }
        const std::string next_type = command.at("value").get<std::string>();
        const auto& fields = detector_fields_or_throw(next_type);
        *target = build_typed_mapping(next_type, fields, target);
        return;
    }
    if (type == "remove_setting") {
        Value* target = resolve_path(document, parse_path(command));
        if (!target->is_mapping()) {
            throw ScenarioEditorError("remove_setting target must be a mapping");
        }
        const std::string key = command.at("key").get<std::string>();
        if (key == "use" || key == "with") {
            throw ScenarioEditorError("shared definition references cannot be removed directly");
        }
        target->erase(key);
        return;
    }
    if (type == "add_condition" || type == "insert_condition") {
        Value* target = resolve_inline_container(document, parse_path(command));
        if (!target->is_mapping()) {
            throw ScenarioEditorError("condition node must be a mapping");
        }
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
        conditions->sequence.insert(
            conditions->sequence.begin() + static_cast<std::ptrdiff_t>(index),
            std::move(value)
        );
        return;
    }
    if (type == "remove_condition") {
        Value* target = resolve_inline_container(document, parse_path(command));
        if (!target->is_mapping()) {
            throw ScenarioEditorError("condition node must be a mapping");
        }
        Value* conditions = target->find("conditions");
        if (conditions == nullptr || !conditions->is_sequence()) {
            throw ScenarioEditorError("conditions must be a sequence");
        }
        const std::size_t index = command.at("index").get<std::size_t>();
        if (index >= conditions->sequence.size()) {
            throw ScenarioEditorError("condition index is out of range");
        }
        conditions->sequence.erase(
            conditions->sequence.begin() + static_cast<std::ptrdiff_t>(index)
        );
        return;
    }
    if (type == "move_condition") {
        Value* target = resolve_inline_container(document, parse_path(command));
        if (!target->is_mapping()) {
            throw ScenarioEditorError("condition node must be a mapping");
        }
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
        conditions->sequence.erase(
            conditions->sequence.begin() + static_cast<std::ptrdiff_t>(from)
        );
        conditions->sequence.insert(
            conditions->sequence.begin() + static_cast<std::ptrdiff_t>(to),
            std::move(moved)
        );
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
        if (!value.is_mapping()) {
            throw ScenarioEditorError("a Condition must be a mapping");
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
        if (command.value("manual", false)) {
            document.splits.insert(
                document.splits.begin() + static_cast<std::ptrdiff_t>(index),
                std::nullopt
            );
        } else {
            document.splits.insert(
                document.splits.begin() + static_cast<std::ptrdiff_t>(index),
                SplitDefinition{}
            );
        }
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
        document.splits.insert(
            document.splits.begin() + static_cast<std::ptrdiff_t>(to),
            std::move(moved)
        );
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
    if (type == "extract_condition_definition") {
        extract_condition_definition(document, command);
        return;
    }
    if (type == "use_condition") {
        Value* target = resolve_path(document, parse_path(command));
        const std::string name = command.at("name").get<std::string>();
        if (find_condition_definition(document, name) == nullptr) {
            throw ScenarioEditorError("condition definition was not found: " + name);
        }
        Value replacement = Value::make_mapping();
        replacement.set("use", Value::make_scalar(name));
        if (target->is_mapping()) {
            const auto* old_use = target->find("use");
            const auto* old_with = target->find("with");
            if (old_use != nullptr && old_use->is_scalar() && old_use->scalar == name
                && old_with != nullptr) {
                replacement.set("with", *old_with);
            }
        }
        *target = std::move(replacement);
        return;
    }
    if (type == "use_detector") {
        Value* target = resolve_path(document, parse_path(command));
        const std::string name = command.at("name").get<std::string>();
        if (find_detector_definition(document, name) == nullptr) {
            throw ScenarioEditorError("detector definition was not found: " + name);
        }
        Value replacement = Value::make_mapping();
        replacement.set("use", Value::make_scalar(name));
        if (target->is_mapping()) {
            const auto* old_use = target->find("use");
            const auto* old_with = target->find("with");
            if (old_use != nullptr && old_use->is_scalar() && old_use->scalar == name
                && old_with != nullptr) {
                replacement.set("with", *old_with);
            }
        }
        *target = std::move(replacement);
        return;
    }
    if (type == "inline_condition") {
        Value* target = resolve_path(document, parse_path(command));
        if (!is_usage_value(*target)) {
            return;
        }
        Value inlined = instantiate_condition_once(document, *target);
        *target = std::move(inlined);
        return;
    }
    if (type == "inline_detector") {
        Value* target = resolve_path(document, parse_path(command));
        if (!is_usage_value(*target)) {
            return;
        }
        *target = resolved_detector(document, *target);
        return;
    }
    if (type == "set_usage_setting") {
        Value* usage = resolve_path(document, parse_path(command));
        set_usage_setting(
            document,
            *usage,
            DefinitionKind::condition,
            setting_path_from_json(command),
            value_from_json(command.at("value"))
        );
        return;
    }
    if (type == "reset_usage_setting") {
        Value* usage = resolve_path(document, parse_path(command));
        reset_usage_setting(
            document,
            *usage,
            DefinitionKind::condition,
            setting_path_from_json(command)
        );
        return;
    }
    if (type == "set_detector_usage_setting") {
        Value* usage = resolve_path(document, parse_path(command));
        set_usage_setting(
            document,
            *usage,
            DefinitionKind::detector,
            setting_path_from_json(command),
            value_from_json(command.at("value"))
        );
        return;
    }
    if (type == "reset_detector_usage_setting") {
        Value* usage = resolve_path(document, parse_path(command));
        reset_usage_setting(
            document,
            *usage,
            DefinitionKind::detector,
            setting_path_from_json(command)
        );
        return;
    }
    if (type == "expose_parameter") {
        expose_parameter(document, command);
        return;
    }
    if (type == "unexpose_parameter") {
        unexpose_parameter(document, command);
        return;
    }
    if (type == "set_definition_setting") {
        set_definition_setting(document, command);
        return;
    }
    if (type == "remove_definition_setting") {
        const DefinitionKind kind = definition_kind_from_command(command);
        const std::string name = command.at("name").get<std::string>();
        const Path setting_path = setting_path_from_json(command);
        const DefinitionRef requested = require_definition(document, kind, name);
        LocatedSetting located = locate_setting(document, requested, setting_path);
        if (!located.chain.empty()) {
            throw ScenarioEditorError(
                "nested definition settings cannot be removed from the outer definition"
            );
        }
        if (located.field != nullptr && located.field->is_parameter_reference()) {
            throw ScenarioEditorError(
                "unexpose the setting before removing the field"
            );
        }
        if (located.field != nullptr) {
            located.parent->erase(located.key);
        }
        return;
    }
    if (type == "create_condition_definition") {
        const std::string name = command.at("name").get<std::string>();
        if (name.empty()) {
            throw ScenarioEditorError("condition definition names must not be empty");
        }
        if (find_condition_definition(document, name) != nullptr) {
            throw ScenarioEditorError("condition definition already exists: " + name);
        }
        Value condition = command.contains("value")
            ? value_from_json(command.at("value"))
            : Value::make_mapping({
                {"type", Value::make_scalar("elapsed")},
                {"duration", Value::make_scalar("1s")},
            });
        if (!condition.is_mapping()) {
            throw ScenarioEditorError("condition definition must be a mapping");
        }
        document.definitions.conditions.push_back(
            scenario::v2::SharedCondition{name, {}, std::move(condition)}
        );
        return;
    }
    if (type == "create_detector_definition") {
        const std::string name = command.at("name").get<std::string>();
        if (name.empty()) {
            throw ScenarioEditorError("detector definition names must not be empty");
        }
        if (find_detector_definition(document, name) != nullptr) {
            throw ScenarioEditorError("detector definition already exists: " + name);
        }
        Value detector = command.contains("value")
            ? value_from_json(command.at("value"))
            : Value::make_mapping({{"type", Value::make_scalar("mean_brightness")}});
        if (!detector.is_mapping()) {
            throw ScenarioEditorError("detector definition must be a mapping");
        }
        document.definitions.detectors.push_back(
            scenario::v2::SharedDetector{name, {}, std::move(detector)}
        );
        return;
    }
    if (type == "rename_condition_definition") {
        const std::string from = command.at("from").get<std::string>();
        const std::string to = command.at("to").get<std::string>();
        if (to.empty()) {
            throw ScenarioEditorError("condition definition names must not be empty");
        }
        auto* definition = find_condition_definition(document, from);
        if (definition == nullptr) {
            throw ScenarioEditorError("condition definition was not found: " + from);
        }
        if (find_condition_definition(document, to) != nullptr) {
            throw ScenarioEditorError("condition definition already exists: " + to);
        }
        definition->name = to;
        visit_all_conditions(document, [&](Value& value) {
            auto* use = value.find("use");
            if (use != nullptr && use->is_scalar() && use->scalar == from) {
                use->scalar = to;
            }
        });
        return;
    }
    if (type == "rename_detector_definition") {
        const std::string from = command.at("from").get<std::string>();
        const std::string to = command.at("to").get<std::string>();
        if (to.empty()) {
            throw ScenarioEditorError("detector definition names must not be empty");
        }
        auto* definition = find_detector_definition(document, from);
        if (definition == nullptr) {
            throw ScenarioEditorError("detector definition was not found: " + from);
        }
        if (find_detector_definition(document, to) != nullptr) {
            throw ScenarioEditorError("detector definition already exists: " + to);
        }
        definition->name = to;
        visit_all_detector_usages(document, [&](Value& value) {
            auto* use = value.find("use");
            if (use != nullptr && use->is_scalar() && use->scalar == from) {
                use->scalar = to;
            }
        });
        return;
    }
    if (type == "delete_condition_definition") {
        const std::string name = command.at("name").get<std::string>();
        if (count_condition_uses(document, name) != 0) {
            throw ScenarioEditorError("condition definition is still in use: " + name);
        }
        auto& definitions = document.definitions.conditions;
        const auto found = std::find_if(
            definitions.begin(), definitions.end(), [&](const auto& definition) {
                return definition.name == name;
            }
        );
        if (found == definitions.end()) {
            throw ScenarioEditorError("condition definition was not found: " + name);
        }
        definitions.erase(found);
        return;
    }
    if (type == "delete_detector_definition") {
        const std::string name = command.at("name").get<std::string>();
        if (count_detector_uses(document, name) != 0) {
            throw ScenarioEditorError("detector definition is still in use: " + name);
        }
        auto& definitions = document.definitions.detectors;
        const auto found = std::find_if(
            definitions.begin(), definitions.end(), [&](const auto& definition) {
                return definition.name == name;
            }
        );
        if (found == definitions.end()) {
            throw ScenarioEditorError("detector definition was not found: " + name);
        }
        definitions.erase(found);
        return;
    }
    throw ScenarioEditorError("unknown editor command: " + type);
}

}  // namespace divergencesplitter::scenario_editor
