#include "divergencesplitter/scenario/editor/document.hpp"

#include <cstddef>
#include <map>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#include "divergencesplitter/scenario/editor/workspace.hpp"
#include "editor_detail.hpp"

namespace divergencesplitter::scenario_editor {
namespace {

using detail::DefinitionKind;
using detail::DefinitionRef;
using detail::Path;
using detail::PathToken;
using detail::expected_kind_for_key;
using detail::find_use_definition;
using detail::is_usage_value;
using detail::traverse;
using detail::value_at_path;

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

nlohmann::json rule_json(const ScenarioDocument& document, const RuleDefinition& rule) {
    return nlohmann::json{
        {"condition", value_to_json(rule.condition.value)},
        {"condition_resolved", value_to_json(resolved_condition(document, rule.condition.value))},
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

nlohmann::json path_to_json(const Path& path) {
    nlohmann::json result = nlohmann::json::array();
    for (const auto& token : path) {
        if (token.is_index) {
            result.push_back(token.index);
        } else {
            result.push_back(token.key);
        }
    }
    return result;
}

Path append_path(const Path& base, const Path& suffix) {
    Path result = base;
    result.insert(result.end(), suffix.begin(), suffix.end());
    return result;
}

void collect_condition_use_paths(
    const Value& value,
    const Path& path,
    std::vector<std::pair<const Value*, Path>>& result
) {
    if (is_usage_value(value)) {
        result.emplace_back(&value, path);
        return;
    }
    if (value.is_sequence()) {
        for (std::size_t index = 0; index < value.sequence.size(); ++index) {
            Path child_path = path;
            child_path.push_back(PathToken{true, index, {}});
            collect_condition_use_paths(value.sequence[index], child_path, result);
        }
        return;
    }
    if (!value.is_mapping()) {
        return;
    }
    for (const auto key : {"condition", "reset_condition", "conditions"}) {
        auto* child = value.find(key);
        if (child != nullptr) {
            Path child_path = path;
            child_path.push_back(PathToken{false, 0, key});
            collect_condition_use_paths(*child, child_path, result);
        }
    }
}

std::map<std::string, std::vector<Path>> parameter_paths_for_definition(
    ScenarioDocument& document,
    DefinitionRef definition
);

void collect_parameter_paths(
    ScenarioDocument& document,
    Value& value,
    Path& path,
    DefinitionKind expected,
    std::map<std::string, std::vector<Path>>& result
) {
    if (value.is_parameter_reference()) {
        result[value.scalar].push_back(path);
        return;
    }
    if (value.is_sequence()) {
        for (std::size_t index = 0; index < value.sequence.size(); ++index) {
            path.push_back(PathToken{true, index, {}});
            collect_parameter_paths(
                document,
                value.sequence[index],
                path,
                expected,
                result
            );
            path.pop_back();
        }
        return;
    }
    if (!value.is_mapping()) {
        return;
    }
    if (is_usage_value(value)) {
        auto child = find_use_definition(document, value, expected);
        if (!child) {
            return;
        }
        const auto child_paths = parameter_paths_for_definition(document, *child);
        const auto* with = value.find("with");
        if (with == nullptr || !with->is_mapping()) {
            return;
        }
        for (const auto& [child_parameter, forwarded] : with->mapping) {
            if (!forwarded.is_parameter_reference()) {
                continue;
            }
            const auto found = child_paths.find(child_parameter);
            if (found == child_paths.end()) {
                continue;
            }
            for (const auto& child_path : found->second) {
                result[forwarded.scalar].push_back(append_path(path, child_path));
            }
        }
        return;
    }
    for (auto& [key, item] : value.mapping) {
        const DefinitionKind child_expected = expected_kind_for_key(key, expected);
        path.push_back(PathToken{false, 0, key});
        collect_parameter_paths(document, item, path, child_expected, result);
        path.pop_back();
    }
}

std::map<std::string, std::vector<Path>> parameter_paths_for_definition(
    ScenarioDocument& document,
    DefinitionRef definition
) {
    std::map<std::string, std::vector<Path>> result;
    Path path;
    collect_parameter_paths(document, *definition.root, path, definition.kind, result);
    return result;
}

nlohmann::json condition_usage_json(
    ScenarioDocument& document,
    const Value& root,
    const std::string& owner_name,
    const Path& absolute_base,
    const Path& relative_path,
    const Value& usage
) {
    const auto* use = usage.find("use");
    if (use == nullptr || !use->is_scalar()) {
        return nullptr;
    }
    auto* definition = find_condition_definition(document, use->scalar);
    if (definition == nullptr) {
        return nullptr;
    }
    const DefinitionRef definition_ref{
        DefinitionKind::condition,
        definition->name,
        &definition->condition,
        &definition->parameters,
    };

    Value resolved_parent = owner_name.empty()
        ? scenario::v2::resolve_condition(document.definitions, root)
        : scenario::v2::resolve_condition(
            document.definitions,
            Value::make_mapping({{"use", Value::make_scalar(owner_name)}})
        );

    Value default_parent;
    if (owner_name.empty()) {
        Value modified_root = root;
        Value* modified_usage = traverse(&modified_root, relative_path, 0);
        modified_usage->erase("with");
        default_parent = scenario::v2::resolve_condition(
            document.definitions,
            modified_root
        );
    } else {
        scenario::v2::Definitions modified_definitions = document.definitions;
        auto* modified_definition = scenario::v2::find_condition(
            modified_definitions,
            owner_name
        );
        if (modified_definition == nullptr) {
            return nullptr;
        }
        Value* modified_usage = traverse(
            &modified_definition->condition,
            relative_path,
            0
        );
        modified_usage->erase("with");
        default_parent = scenario::v2::resolve_condition(
            modified_definitions,
            Value::make_mapping({{"use", Value::make_scalar(owner_name)}})
        );
    }

    const Value null_value = Value::make_null();
    const Value* resolved = value_at_path(resolved_parent, relative_path);
    const Value* default_resolved = value_at_path(default_parent, relative_path);
    const auto parameter_paths = parameter_paths_for_definition(
        document,
        definition_ref
    );

    nlohmann::json overrides = nlohmann::json::array();
    const auto* with = usage.find("with");
    if (with != nullptr && with->is_mapping()) {
        for (const auto& [parameter, forwarded] : with->mapping) {
            if (forwarded.is_parameter_reference()) {
                continue;
            }
            const auto found = parameter_paths.find(parameter);
            if (found == parameter_paths.end()) {
                continue;
            }
            for (const auto& setting_path : found->second) {
                const Value* current = resolved == nullptr
                    ? nullptr
                    : value_at_path(*resolved, setting_path);
                const Value* default_value = default_resolved == nullptr
                    ? nullptr
                    : value_at_path(*default_resolved, setting_path);
                overrides.push_back(nlohmann::json{
                    {"parameter", parameter},
                    {"path", path_to_json(setting_path)},
                    {"default", value_to_json(
                        default_value == nullptr ? null_value : *default_value
                    )},
                    {"value", value_to_json(
                        current == nullptr ? null_value : *current
                    )},
                });
            }
        }
    }

    return nlohmann::json{
        {"path", path_to_json(append_path(absolute_base, relative_path))},
        {"name", definition->name},
        {"resolved", value_to_json(resolved == nullptr ? null_value : *resolved)},
        {"default_resolved", value_to_json(
            default_resolved == nullptr ? null_value : *default_resolved
        )},
        {"overrides", std::move(overrides)},
    };
}

void append_condition_usages(
    ScenarioDocument& document,
    const Value& root,
    const std::string& owner_name,
    const Path& absolute_base,
    nlohmann::json& result
) {
    std::vector<std::pair<const Value*, Path>> usages;
    collect_condition_use_paths(root, Path{}, usages);
    for (const auto& [usage, relative_path] : usages) {
        nlohmann::json entry = condition_usage_json(
            document,
            root,
            owner_name,
            absolute_base,
            relative_path,
            *usage
        );
        if (!entry.is_null()) {
            result.push_back(std::move(entry));
        }
    }
}

nlohmann::json condition_usages_json(ScenarioDocument& document) {
    nlohmann::json result = nlohmann::json::array();
    for (auto& definition : document.definitions.conditions) {
        append_condition_usages(
            document,
            definition.condition,
            definition.name,
            Path{
                PathToken{false, 0, "definitions"},
                PathToken{false, 0, "conditions"},
                PathToken{false, 0, definition.name},
            },
            result
        );
    }
    if (document.start_condition) {
        append_condition_usages(
            document,
            document.start_condition->value,
            "",
            Path{PathToken{false, 0, "start_condition"}},
            result
        );
    }
    if (document.reset_condition) {
        append_condition_usages(
            document,
            document.reset_condition->value,
            "",
            Path{PathToken{false, 0, "reset_condition"}},
            result
        );
    }
    if (document.incomplete_condition) {
        append_condition_usages(
            document,
            document.incomplete_condition->value,
            "",
            Path{PathToken{false, 0, "incomplete_condition"}},
            result
        );
    }
    for (std::size_t split_index = 0; split_index < document.splits.size(); ++split_index) {
        const auto& split = document.splits[split_index];
        if (!split) {
            continue;
        }
        for (std::size_t rule_index = 0; rule_index < split->rules.size(); ++rule_index) {
            const auto& rule = split->rules[rule_index];
            if (rule.sequence) {
                for (std::size_t step_index = 0;
                     step_index < rule.sequence_rules.size();
                     ++step_index) {
                    Path path{
                        PathToken{false, 0, "splits"},
                        PathToken{true, split_index, {}},
                        PathToken{false, 0, "rules"},
                        PathToken{true, rule_index, {}},
                        PathToken{false, 0, "sequence"},
                        PathToken{true, step_index, {}},
                        PathToken{false, 0, "condition"},
                    };
                    append_condition_usages(
                        document,
                        rule.sequence_rules[step_index].condition.value,
                        "",
                        path,
                        result
                    );
                }
            } else {
                Path path{
                    PathToken{false, 0, "splits"},
                    PathToken{true, split_index, {}},
                    PathToken{false, 0, "rules"},
                    PathToken{true, rule_index, {}},
                    PathToken{false, 0, "condition"},
                };
                append_condition_usages(
                    document,
                    rule.rule.condition.value,
                    "",
                    path,
                    result
                );
            }
        }
    }
    return result;
}

nlohmann::json parameters_json(
    const std::vector<scenario::v2::ParameterDefinition>& parameters
) {
    nlohmann::json result = nlohmann::json::array();
    for (const auto& parameter : parameters) {
        result.push_back(nlohmann::json{
            {"name", parameter.name},
            {"default", value_to_json(parameter.default_value)},
        });
    }
    return result;
}

nlohmann::json resolved_usage_json(
    const ScenarioDocument& document,
    const std::optional<ConditionUsage>& usage
) {
    if (!usage) {
        return nullptr;
    }
    return value_to_json(resolved_condition(document, usage->value));
}

}  // namespace

nlohmann::json editor_state_json(const EditorSession& session) {
    ScenarioDocument metadata_document = session.document;
    const nlohmann::json condition_usages = condition_usages_json(metadata_document);
    nlohmann::json condition_definitions = nlohmann::json::array();
    for (const auto& definition : session.document.definitions.conditions) {
        const auto resolved = scenario::v2::resolve_condition(
            session.document.definitions,
            Value::make_mapping({{"use", Value::make_scalar(definition.name)}})
        );
        condition_definitions.push_back(nlohmann::json{
            {"name", definition.name},
            {"parameters", parameters_json(definition.parameters)},
            {"condition", value_to_json(definition.condition)},
            {"condition_resolved", value_to_json(resolved)},
        });
    }
    nlohmann::json detector_definitions = nlohmann::json::array();
    for (const auto& definition : session.document.definitions.detectors) {
        const auto resolved = scenario::v2::resolve_detector(
            session.document.definitions,
            Value::make_mapping({{"use", Value::make_scalar(definition.name)}})
        );
        detector_definitions.push_back(nlohmann::json{
            {"name", definition.name},
            {"parameters", parameters_json(definition.parameters)},
            {"detector", value_to_json(definition.detector)},
            {"detector_resolved", value_to_json(resolved)},
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
        {"condition_usages", condition_usages},
        {"definitions", nlohmann::json{
            {"conditions", std::move(condition_definitions)},
            {"detectors", std::move(detector_definitions)},
        }},
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
        {"version", 3},
        {"schema", editor_schema_json()},
        {"document", std::move(document)},
        {"canUndo", !session.undo_stack.empty()},
        {"canRedo", !session.redo_stack.empty()},
    };
}

}  // namespace divergencesplitter::scenario_editor
