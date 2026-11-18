#include "divergencesplitter/scenario/editor/model.hpp"

#include <set>
#include <string>
#include <utility>
#include <vector>

namespace divergencesplitter::scenario_editor {
namespace {

Value rule_to_value(const RuleDefinition& rule) {
    Value result = Value::make_mapping();
    result.set("condition", rule.condition.value);
    result.set("action", Value::make_scalar(rule.action));
    return result;
}

Value scenario_rule_to_value(const ScenarioRule& rule) {
    if (!rule.sequence) {
        return rule_to_value(rule.rule);
    }
    Value sequence = Value::make_sequence();
    sequence.sequence.reserve(rule.sequence_rules.size());
    for (const auto& step : rule.sequence_rules) {
        sequence.sequence.push_back(rule_to_value(step));
    }
    Value result = Value::make_mapping();
    result.set("sequence", std::move(sequence));
    return result;
}

Value splits_to_value(
    const std::vector<std::optional<SplitDefinition>>& splits
) {
    Value result = Value::make_sequence();
    result.sequence.reserve(splits.size());
    for (const auto& split : splits) {
        if (!split) {
            result.sequence.push_back(Value::make_null());
            continue;
        }
        Value rules = Value::make_sequence();
        rules.sequence.reserve(split->rules.size());
        for (const auto& rule : split->rules) {
            rules.sequence.push_back(scenario_rule_to_value(rule));
        }
        Value item = Value::make_mapping();
        item.set("rules", std::move(rules));
        result.sequence.push_back(std::move(item));
    }
    return result;
}

void validate_definition_parameters(const scenario::v2::Definitions& definitions) {
    const auto check = [](const auto& definition) {
        std::set<std::string> names;
        for (const auto& parameter : definition.parameters) {
            if (parameter.name.empty()) {
                throw ScenarioEditorError("parameter names must not be empty");
            }
            if (!names.insert(parameter.name).second) {
                throw ScenarioEditorError(
                    "parameter is duplicated in " + definition.name + ": " + parameter.name
                );
            }
        }
    };
    for (const auto& definition : definitions.conditions) {
        if (definition.name.empty()) {
            throw ScenarioEditorError("condition definition names must not be empty");
        }
        check(definition);
    }
    for (const auto& definition : definitions.detectors) {
        if (definition.name.empty()) {
            throw ScenarioEditorError("detector definition names must not be empty");
        }
        check(definition);
    }
}

void validate_extra_root(const ScenarioDocument& document) {
    static const std::set<std::string_view> reserved{
        "schema_version",
        "definitions",
        "start_condition",
        "reset_condition",
        "incomplete_condition",
        "splits",
    };
    std::set<std::string> keys;
    for (const auto& [key, value] : document.extra_root) {
        (void)value;
        if (key.empty() || reserved.contains(key)) {
            throw ScenarioEditorError("invalid extra root field: " + key);
        }
        if (!keys.insert(key).second) {
            throw ScenarioEditorError("extra root field is duplicated: " + key);
        }
    }
}

}  // namespace

bool ConditionUsage::is_shared_use() const noexcept {
    return value.is_mapping() && value.find("use") != nullptr;
}

std::string ConditionUsage::use_name() const {
    if (!is_shared_use()) {
        return {};
    }
    const auto* use = value.find("use");
    return use->is_scalar() ? use->scalar : std::string{};
}

const Value* ConditionUsage::with() const {
    return is_shared_use() ? value.find("with") : nullptr;
}

const scenario::v2::SharedCondition* find_condition_definition(
    const ScenarioDocument& document,
    std::string_view name
) {
    return scenario::v2::find_condition(document.definitions, name);
}

scenario::v2::SharedCondition* find_condition_definition(
    ScenarioDocument& document,
    std::string_view name
) {
    return scenario::v2::find_condition(document.definitions, name);
}

const scenario::v2::SharedDetector* find_detector_definition(
    const ScenarioDocument& document,
    std::string_view name
) {
    return scenario::v2::find_detector(document.definitions, name);
}

scenario::v2::SharedDetector* find_detector_definition(
    ScenarioDocument& document,
    std::string_view name
) {
    return scenario::v2::find_detector(document.definitions, name);
}

Value resolved_condition(const ScenarioDocument& document, const Value& usage) {
    return scenario::v2::resolve_condition(document.definitions, usage);
}

Value resolved_detector(const ScenarioDocument& document, const Value& usage) {
    return scenario::v2::resolve_detector(document.definitions, usage);
}

scenario::v2::Document to_v2_document(const ScenarioDocument& document) {
    scenario::v2::Document result;
    result.definitions = document.definitions;
    if (document.start_condition) {
        result.start_condition = document.start_condition->value;
    } else {
        result.start_condition = Value::make_null();
    }
    if (document.reset_condition) {
        result.reset_condition = document.reset_condition->value;
    }
    if (document.incomplete_condition) {
        result.incomplete_condition = document.incomplete_condition->value;
    }
    result.splits = splits_to_value(document.splits);
    result.extra_root = document.extra_root;
    return result;
}

void validate_scenario_document(const ScenarioDocument& document) {
    validate_definition_parameters(document.definitions);
    validate_extra_root(document);

    const auto v2_document = to_v2_document(document);
    scenario::v2::validate_document(v2_document);

    for (const auto& definition : document.definitions.conditions) {
        const auto resolved = scenario::v2::resolve_condition(
            document.definitions,
            Value::make_mapping({{"use", Value::make_scalar(definition.name)}})
        );
        validate_condition_schema(resolved);
    }
    for (const auto& definition : document.definitions.detectors) {
        const auto resolved = scenario::v2::resolve_detector(
            document.definitions,
            Value::make_mapping({{"use", Value::make_scalar(definition.name)}})
        );
        validate_detector_schema(resolved);
    }

    const auto validate_usage = [&](const std::optional<ConditionUsage>& usage) {
        if (!usage) {
            return;
        }
        validate_condition_schema(resolved_condition(document, usage->value));
    };
    validate_usage(document.start_condition);
    validate_usage(document.reset_condition);
    validate_usage(document.incomplete_condition);
    for (const auto& split : document.splits) {
        if (!split) {
            continue;
        }
        for (const auto& rule : split->rules) {
            if (rule.sequence) {
                for (const auto& step : rule.sequence_rules) {
                    validate_condition_schema(
                        resolved_condition(document, step.condition.value)
                    );
                }
            } else {
                validate_condition_schema(
                    resolved_condition(document, rule.rule.condition.value)
                );
            }
        }
    }

    std::set<std::string> condition_names;
    for (const auto& definition : document.definitions.conditions) {
        if (!condition_names.insert(definition.name).second) {
            throw ScenarioEditorError(
                "condition definition is duplicated: " + definition.name
            );
        }
    }
    std::set<std::string> detector_names;
    for (const auto& definition : document.definitions.detectors) {
        if (!detector_names.insert(definition.name).second) {
            throw ScenarioEditorError(
                "detector definition is duplicated: " + definition.name
            );
        }
    }
}

}  // namespace divergencesplitter::scenario_editor
