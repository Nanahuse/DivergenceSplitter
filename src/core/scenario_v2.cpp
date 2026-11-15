#include "divergencesplitter/scenario/v2.hpp"

#include <map>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace divergencesplitter::scenario::v2 {
namespace {

using Bindings = std::map<std::string, Value>;

[[noreturn]] void v2_error(const std::string& message) {
    throw std::runtime_error("scenario v2: " + message);
}

struct Context {
    const Definitions& definitions;
    const Bindings* bindings{};
    std::string owner;
    std::set<std::string> definition_stack;
    std::set<std::string> parameter_stack;
};

const std::string& require_use_name(const Value& usage) {
    const auto* use = usage.find("use");
    if (use == nullptr || !use->is_scalar() || use->scalar.empty()) {
        v2_error("use must be a non-empty definition name");
    }
    return use->scalar;
}

void validate_usage_keys(const Value& usage) {
    for (const auto& [key, item] : usage.mapping) {
        (void)item;
        if (key != "use" && key != "with") {
            v2_error("shared definition usage only supports use and with: " + key);
        }
    }
}

Bindings make_bindings(
    const Context& caller,
    const std::vector<ParameterDefinition>& parameters,
    const Value* with,
    const std::string& owner
);

Value resolve_value(const Value& value, const Context& context);

Value resolve_condition_node(const Value& value, const Context& context);
Value resolve_detector_node(const Value& value, const Context& context);

Bindings make_bindings(
    const Context& caller,
    const std::vector<ParameterDefinition>& parameters,
    const Value* with,
    const std::string& owner
) {
    Bindings bindings;
    for (const auto& parameter : parameters) {
        if (parameter.name.empty()) {
            v2_error("parameter names must not be empty");
        }
        if (!bindings.emplace(parameter.name, parameter.default_value).second) {
            v2_error("parameter is defined more than once: " + parameter.name);
        }
    }
    if (with == nullptr) {
        return bindings;
    }
    if (!with->is_mapping()) {
        v2_error(owner + ".with must be a mapping");
    }
    for (const auto& [name, value] : with->mapping) {
        if (!bindings.contains(name)) {
            v2_error(owner + ".with contains an unknown parameter: " + name);
        }
        bindings[name] = resolve_value(value, caller);
    }
    return bindings;
}

Value resolve_value(const Value& value, const Context& context) {
    switch (value.kind) {
    case ValueKind::parameter_reference: {
        if (context.bindings == nullptr) {
            v2_error("parameter reference has no binding scope: " + value.scalar);
        }
        const auto found = context.bindings->find(value.scalar);
        if (found == context.bindings->end()) {
            v2_error("parameter is not defined in this scope: " + value.scalar);
        }
        const std::string key = context.owner + "::" + value.scalar;
        Context nested = context;
        if (!nested.parameter_stack.insert(key).second) {
            v2_error("cyclic parameter reference: " + value.scalar);
        }
        Value resolved = resolve_value(found->second, nested);
        return resolved;
    }
    case ValueKind::sequence: {
        Value result = Value::make_sequence();
        result.sequence.reserve(value.sequence.size());
        for (const auto& item : value.sequence) {
            result.sequence.push_back(resolve_value(item, context));
        }
        return result;
    }
    case ValueKind::mapping: {
        Value result = Value::make_mapping();
        result.mapping.reserve(value.mapping.size());
        for (const auto& [key, item] : value.mapping) {
            result.mapping.emplace_back(key, resolve_value(item, context));
        }
        return result;
    }
    case ValueKind::null_value:
    case ValueKind::scalar:
        return value;
    case ValueKind::alias:
        v2_error("YAML aliases are not supported in v2 scenarios; use definitions/use");
    }
    v2_error("unsupported value");
}

Value resolve_condition_node(const Value& value, const Context& context) {
    if (!value.is_mapping()) {
        if (value.is_parameter_reference()) {
            v2_error("conditions cannot be passed as parameters");
        }
        v2_error("condition must be a mapping");
    }
    if (value.find("use") != nullptr) {
        validate_usage_keys(value);
        const std::string& name = require_use_name(value);
        const auto* definition = find_condition(context.definitions, name);
        if (definition == nullptr) {
            if (find_detector(context.definitions, name) != nullptr) {
                v2_error("condition use refers to a detector definition: " + name);
            }
            v2_error("condition definition was not found: " + name);
        }
        const std::string key = "condition:" + name;
        if (context.definition_stack.contains(key)) {
            v2_error("cyclic condition definition: " + name);
        }
        const auto bindings = make_bindings(
            context,
            definition->parameters,
            value.find("with"),
            "condition " + name
        );
        Context nested = context;
        nested.bindings = &bindings;
        nested.owner = key;
        nested.definition_stack.insert(key);
        return resolve_condition_node(definition->condition, nested);
    }

    Value result = Value::make_mapping();
    result.mapping.reserve(value.mapping.size());
    for (const auto& [key, item] : value.mapping) {
        if (key == "condition" || key == "reset_condition") {
            result.mapping.emplace_back(key, resolve_condition_node(item, context));
        } else if (key == "conditions") {
            if (!item.is_sequence()) {
                v2_error("conditions must be a list");
            }
            Value conditions = Value::make_sequence();
            conditions.sequence.reserve(item.sequence.size());
            for (const auto& child : item.sequence) {
                conditions.sequence.push_back(resolve_condition_node(child, context));
            }
            result.mapping.emplace_back(key, std::move(conditions));
        } else if (key == "detector") {
            result.mapping.emplace_back(key, resolve_detector_node(item, context));
        } else {
            result.mapping.emplace_back(key, resolve_value(item, context));
        }
    }
    return result;
}

Value resolve_detector_node(const Value& value, const Context& context) {
    if (!value.is_mapping()) {
        v2_error("detector must be a mapping");
    }
    if (value.find("use") != nullptr) {
        validate_usage_keys(value);
        const std::string& name = require_use_name(value);
        const auto* definition = find_detector(context.definitions, name);
        if (definition == nullptr) {
            if (find_condition(context.definitions, name) != nullptr) {
                v2_error("detector use refers to a condition definition: " + name);
            }
            v2_error("detector definition was not found: " + name);
        }
        const std::string key = "detector:" + name;
        if (context.definition_stack.contains(key)) {
            v2_error("cyclic detector definition: " + name);
        }
        const auto bindings = make_bindings(
            context,
            definition->parameters,
            value.find("with"),
            "detector " + name
        );
        Context nested = context;
        nested.bindings = &bindings;
        nested.owner = key;
        nested.definition_stack.insert(key);
        return resolve_detector_node(definition->detector, nested);
    }

    Value result = Value::make_mapping();
    result.mapping.reserve(value.mapping.size());
    for (const auto& [key, item] : value.mapping) {
        result.mapping.emplace_back(key, resolve_value(item, context));
    }
    return result;
}

Value normalize_splits(const Definitions& definitions, const Value& splits) {
    if (!splits.is_sequence()) {
        v2_error("splits must be a list");
    }
    const Bindings empty;
    const Context context{definitions, &empty, "", {}, {}};
    Value result = Value::make_sequence();
    result.sequence.reserve(splits.sequence.size());
    for (const auto& split : splits.sequence) {
        if (split.is_null()) {
            result.sequence.push_back(Value::make_null());
            continue;
        }
        if (!split.is_mapping()) {
            v2_error("split must be a mapping or null");
        }
        Value normalized_split = split;
        auto* rules = normalized_split.find("rules");
        if (rules == nullptr || !rules->is_sequence()) {
            v2_error("split.rules must be a list");
        }
        Value normalized_rules = Value::make_sequence();
        normalized_rules.sequence.reserve(rules->sequence.size());
        for (const auto& rule : rules->sequence) {
            if (!rule.is_mapping()) {
                v2_error("rule must be a mapping");
            }
            Value normalized_rule = rule;
            if (auto* sequence = normalized_rule.find("sequence"); sequence != nullptr) {
                if (!sequence->is_sequence()) {
                    v2_error("rule.sequence must be a list");
                }
                Value steps = Value::make_sequence();
                steps.sequence.reserve(sequence->sequence.size());
                for (const auto& step : sequence->sequence) {
                    if (!step.is_mapping()) {
                        v2_error("rule sequence step must be a mapping");
                    }
                    Value normalized_step = step;
                    auto* condition = normalized_step.find("condition");
                    if (condition == nullptr) {
                        v2_error("rule condition is missing");
                    }
                    *condition = resolve_condition_node(*condition, context);
                    steps.sequence.push_back(std::move(normalized_step));
                }
                *sequence = std::move(steps);
            } else {
                auto* condition = normalized_rule.find("condition");
                if (condition == nullptr) {
                    v2_error("rule condition is missing");
                }
                *condition = resolve_condition_node(*condition, context);
            }
            normalized_rules.sequence.push_back(std::move(normalized_rule));
        }
        *rules = std::move(normalized_rules);
        result.sequence.push_back(std::move(normalized_split));
    }
    return result;
}

std::vector<ParameterDefinition> parse_parameters(const Value* parameters, const std::string& owner) {
    std::vector<ParameterDefinition> result;
    if (parameters == nullptr) {
        return result;
    }
    if (!parameters->is_mapping()) {
        v2_error(owner + ".parameters must be a mapping");
    }
    std::set<std::string> names;
    for (const auto& [name, value] : parameters->mapping) {
        if (name.empty()) {
            v2_error(owner + ".parameters names must not be empty");
        }
        if (!names.insert(name).second) {
            v2_error(owner + ".parameters contains a duplicate name: " + name);
        }
        result.push_back(ParameterDefinition{name, value});
    }
    return result;
}

Value require_node(const Value& entry, std::string_view key, const std::string& owner) {
    const auto* value = entry.find(key);
    if (value == nullptr || value->is_null()) {
        v2_error(owner + "." + std::string(key) + " is required");
    }
    return *value;
}

void validate_definition_keys(
    const Value& entry,
    std::string_view value_key,
    const std::string& owner
) {
    for (const auto& [key, item] : entry.mapping) {
        (void)item;
        if (key != "parameters" && key != value_key) {
            v2_error(owner + " contains an unknown field: " + key);
        }
    }
}

}  // namespace

const SharedCondition* find_condition(const Definitions& definitions, std::string_view name) {
    for (const auto& definition : definitions.conditions) {
        if (definition.name == name) {
            return &definition;
        }
    }
    return nullptr;
}

SharedCondition* find_condition(Definitions& definitions, std::string_view name) {
    for (auto& definition : definitions.conditions) {
        if (definition.name == name) {
            return &definition;
        }
    }
    return nullptr;
}

const SharedDetector* find_detector(const Definitions& definitions, std::string_view name) {
    for (const auto& definition : definitions.detectors) {
        if (definition.name == name) {
            return &definition;
        }
    }
    return nullptr;
}

SharedDetector* find_detector(Definitions& definitions, std::string_view name) {
    for (auto& definition : definitions.detectors) {
        if (definition.name == name) {
            return &definition;
        }
    }
    return nullptr;
}

Document parse_document(const Value& root) {
    if (!root.is_mapping()) {
        v2_error("document must be a mapping");
    }
    const auto* version = root.find("schema_version");
    if (version == nullptr || !version->is_scalar() || version->scalar != "2") {
        v2_error("schema_version must be 2");
    }

    Document document;
    std::set<std::string> condition_names;
    std::set<std::string> detector_names;
    if (const auto* definitions = root.find("definitions"); definitions != nullptr) {
        if (!definitions->is_mapping()) {
            v2_error("definitions must be a mapping");
        }
        for (const auto& [section, item] : definitions->mapping) {
            if (section != "conditions" && section != "detectors") {
                v2_error("unknown definitions section: " + section);
            }
            if (!item.is_mapping()) {
                v2_error("definitions." + section + " must be a mapping");
            }
            if (section == "conditions") {
                for (const auto& [name, entry] : item.mapping) {
                    if (name.empty()) {
                        v2_error("condition definition names must not be empty");
                    }
                    if (!condition_names.insert(name).second) {
                        v2_error("condition definition is duplicated: " + name);
                    }
                    if (!entry.is_mapping()) {
                        v2_error("condition definition must be a mapping: " + name);
                    }
                    validate_definition_keys(entry, "condition", "condition definition " + name);
                    document.definitions.conditions.push_back(SharedCondition{
                        name,
                        parse_parameters(entry.find("parameters"), "condition definition " + name),
                        require_node(entry, "condition", "condition definition " + name),
                    });
                }
            } else {
                for (const auto& [name, entry] : item.mapping) {
                    if (name.empty()) {
                        v2_error("detector definition names must not be empty");
                    }
                    if (!detector_names.insert(name).second) {
                        v2_error("detector definition is duplicated: " + name);
                    }
                    if (!entry.is_mapping()) {
                        v2_error("detector definition must be a mapping: " + name);
                    }
                    validate_definition_keys(entry, "detector", "detector definition " + name);
                    document.definitions.detectors.push_back(SharedDetector{
                        name,
                        parse_parameters(entry.find("parameters"), "detector definition " + name),
                        require_node(entry, "detector", "detector definition " + name),
                    });
                }
            }
        }
    }

    document.start_condition = require_node(root, "start_condition", "scenario");
    if (const auto* reset = root.find("reset_condition"); reset != nullptr && !reset->is_null()) {
        document.reset_condition = *reset;
    }
    if (const auto* incomplete = root.find("incomplete_condition");
        incomplete != nullptr && !incomplete->is_null()) {
        document.incomplete_condition = *incomplete;
    }
    document.splits = require_node(root, "splits", "scenario");
    if (!document.splits.is_sequence()) {
        v2_error("scenario.splits must be a list");
    }
    for (const auto& [key, value] : root.mapping) {
        if (key == "schema_version" || key == "definitions" || key == "start_condition"
            || key == "reset_condition" || key == "incomplete_condition" || key == "splits") {
            continue;
        }
        document.extra_root.emplace_back(key, value);
    }
    return document;
}

Value resolve_condition(const Definitions& definitions, const Value& usage) {
    const Bindings empty;
    const Context context{definitions, &empty, "", {}, {}};
    return resolve_condition_node(usage, context);
}

Value resolve_detector(const Definitions& definitions, const Value& usage) {
    const Bindings empty;
    const Context context{definitions, &empty, "", {}, {}};
    return resolve_detector_node(usage, context);
}

Value normalize_scenario(const Document& document) {
    Value result = Value::make_mapping();
    result.set("start_condition", resolve_condition(document.definitions, document.start_condition));
    if (document.reset_condition) {
        result.set(
            "reset_condition",
            resolve_condition(document.definitions, *document.reset_condition)
        );
    }
    if (document.incomplete_condition) {
        result.set(
            "incomplete_condition",
            resolve_condition(document.definitions, *document.incomplete_condition)
        );
    }
    result.set("splits", normalize_splits(document.definitions, document.splits));
    return result;
}

void validate_document(const Document& document) {
    for (const auto& definition : document.definitions.conditions) {
        Value usage = Value::make_mapping({{"use", Value::make_scalar(definition.name)}});
        (void)resolve_condition(document.definitions, usage);
    }
    for (const auto& definition : document.definitions.detectors) {
        Value usage = Value::make_mapping({{"use", Value::make_scalar(definition.name)}});
        (void)resolve_detector(document.definitions, usage);
    }
    (void)normalize_scenario(document);
}

}  // namespace divergencesplitter::scenario::v2
