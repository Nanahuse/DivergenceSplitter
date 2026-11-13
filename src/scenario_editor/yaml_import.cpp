#include "divergencesplitter/scenario/editor/document.hpp"

#include <ryml/ryml.hpp>
#include <ryml/ryml_std.hpp>

#include <algorithm>
#include <fstream>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <utility>
#include <vector>

#include "../core/scenario_yaml.hpp"

namespace divergencesplitter::scenario_editor {
namespace {

using ryml::ConstNodeRef;

[[noreturn]] void yaml_error(const std::string& message) {
    throw ScenarioEditorError("could not parse scenario YAML: " + message);
}

ryml::Callbacks yaml_callbacks() {
    ryml::Callbacks callbacks;
    callbacks.set_error_basic([](ryml::csubstr message, const ryml::ErrorDataBasic&, void*) {
        yaml_error(scenario_yaml::copy_scalar(message));
    });
    callbacks.set_error_parse([](ryml::csubstr message, const ryml::ErrorDataParse& data, void*) {
        yaml_error(
            scenario_yaml::copy_scalar(message) + " at line " + std::to_string(data.ymlloc.line + 1)
            + ", column " + std::to_string(data.ymlloc.col + 1)
        );
    });
    callbacks.set_error_visit([](ryml::csubstr message, const ryml::ErrorDataVisit&, void*) {
        yaml_error(scenario_yaml::copy_scalar(message));
    });
    return callbacks;
}

using AnchorMap = std::map<std::string, ConstNodeRef>;

void check_unique_keys(ConstNodeRef node, const std::string& path) {
    std::set<std::string> keys;
    for (const auto entry : node.children()) {
        if (entry.is_key_ref()) {
            yaml_error(path + " aliases as mapping keys are not supported");
        }
        if (!entry.has_key() || entry.key_is_null()) {
            yaml_error(path + " mapping keys must be strings");
        }
        const std::string key = scenario_yaml::copy_scalar(entry.key());
        if (!keys.insert(key).second) {
            yaml_error(path + "." + key + " is duplicated");
        }
    }
}

std::optional<std::string> node_anchor(ConstNodeRef node) {
    if (!node.has_val_anchor()) {
        return std::nullopt;
    }
    const std::string name = scenario_yaml::copy_scalar(node.val_anchor());
    if (name.empty()) {
        yaml_error("anchor names must not be empty");
    }
    return name;
}

void collect_anchors(ConstNodeRef node, AnchorMap& anchors) {
    if (node.has_key_anchor()) {
        yaml_error("anchors on mapping keys are not supported by the Scenario Builder");
    }
    if (const auto name = node_anchor(node)) {
        if (!node.is_map()) {
            yaml_error("anchor '" + *name + "' must be attached to a mapping");
        }
        if (!anchors.emplace(*name, node).second) {
            yaml_error("anchor is defined more than once: " + *name);
        }
    }
    for (const auto child : node.children()) {
        collect_anchors(child, anchors);
    }
}

void collect_structural_ids(ConstNodeRef root, std::set<ryml::id_type>& ids) {
    ids.insert(root.id());
    if (const auto definitions = scenario_yaml::child(root, "definitions");
        !definitions.invalid()) {
        ids.insert(definitions.id());
    }
    const auto splits = scenario_yaml::child(root, "splits");
    if (splits.invalid() || !splits.is_seq()) {
        return;
    }
    ids.insert(splits.id());
    for (const auto split : splits.children()) {
        ids.insert(split.id());
        if (!split.is_map()) {
            continue;
        }
        const auto rules = scenario_yaml::child(split, "rules");
        if (rules.invalid() || !rules.is_seq()) {
            continue;
        }
        ids.insert(rules.id());
        for (const auto rule : rules.children()) {
            ids.insert(rule.id());
            const auto sequence = scenario_yaml::child(rule, "sequence");
            if (!sequence.invalid()) {
                ids.insert(sequence.id());
                for (const auto step : sequence.children()) {
                    ids.insert(step.id());
                }
            }
        }
    }
}

Value value_from_node(
    ConstNodeRef node,
    const AnchorMap& anchors,
    std::set<std::string>& expanding,
    const std::string& path,
    std::optional<ryml::id_type> ignored_anchor = std::nullopt
);

Value value_from_map(
    ConstNodeRef node,
    const AnchorMap& anchors,
    std::set<std::string>& expanding,
    const std::string& path,
    std::optional<ryml::id_type> ignored_anchor
) {
    Value result = Value::make_mapping();
    std::set<std::string> source_keys;
    for (const auto entry : node.children()) {
        if (entry.is_key_ref()) {
            yaml_error(path + " aliases as mapping keys are not supported");
        }
        if (!entry.has_key() || entry.key_is_null()) {
            yaml_error(path + " mapping keys must be strings");
        }
        const std::string key = scenario_yaml::copy_scalar(entry.key());
        if (!source_keys.insert(key).second) {
            yaml_error(path + "." + key + " is duplicated");
        }
        if (key == "<<") {
            const auto merge_one = [&](ConstNodeRef reference) {
                if (!reference.is_val_ref()) {
                    yaml_error(path + " merge values must be aliases to mappings");
                }
                const std::string anchor = scenario_yaml::copy_scalar(reference.val_ref());
                const auto target = anchors.find(anchor);
                if (target == anchors.end()) {
                    yaml_error(path + " merge alias not found: " + anchor);
                }
                if (!expanding.insert(anchor).second) {
                    yaml_error(path + " cyclic merge alias: " + anchor);
                }
                Value merged = value_from_node(
                    target->second,
                    anchors,
                    expanding,
                    path + ".<<",
                    target->second.id()
                );
                expanding.erase(anchor);
                if (!merged.is_mapping()) {
                    yaml_error(path + " merge alias must refer to a mapping: " + anchor);
                }
                for (auto& [merged_key, merged_value] : merged.mapping) {
                    result.set(std::move(merged_key), std::move(merged_value));
                }
            };
            if (entry.is_seq()) {
                for (const auto item : entry.children()) {
                    merge_one(item);
                }
            } else {
                merge_one(entry);
            }
            continue;
        }
        result.set(
            key,
            value_from_node(entry, anchors, expanding, path + "." + key, ignored_anchor)
        );
    }
    return result;
}

Value value_from_node(
    ConstNodeRef node,
    const AnchorMap& anchors,
    std::set<std::string>& expanding,
    const std::string& path,
    std::optional<ryml::id_type> ignored_anchor
) {
    if (node.is_val_ref()) {
        return Value::make_alias(scenario_yaml::copy_scalar(node.val_ref()));
    }
    if (const auto name = node_anchor(node);
        name && (!ignored_anchor || node.id() != *ignored_anchor)) {
        return Value::make_alias(*name);
    }
    if (node.is_map()) {
        return value_from_map(node, anchors, expanding, path, ignored_anchor);
    }
    if (node.is_seq()) {
        Value result = Value::make_sequence();
        std::size_t index = 0;
        for (const auto item : node.children()) {
            result.sequence.push_back(value_from_node(
                item,
                anchors,
                expanding,
                path + "[" + std::to_string(index++) + "]",
                ignored_anchor
            ));
        }
        return result;
    }
    if (node.invalid() || scenario_yaml::is_null(node)) {
        return Value::make_null();
    }
    if (!node.has_val()) {
        yaml_error(path + " must be a scalar or mapping");
    }
    return Value::make_scalar(scenario_yaml::copy_scalar(node.val()));
}

std::optional<ConditionUsage> condition_usage(
    ConstNodeRef node,
    const AnchorMap& anchors,
    std::set<std::string>& expanding,
    const std::string& path
) {
    if (node.invalid() || scenario_yaml::is_null(node)) {
        return std::nullopt;
    }
    ConditionUsage usage{value_from_node(node, anchors, expanding, path)};
    if (!usage.value.is_mapping() && !usage.value.is_alias()) {
        throw ScenarioEditorError(path + " must be a Condition mapping or alias");
    }
    return usage;
}

std::string scalar_field(ConstNodeRef node, std::string_view key, const std::string& path) {
    const auto value = scenario_yaml::child(node, key);
    if (value.invalid() || !value.has_val() || scenario_yaml::is_null(value)) {
        throw ScenarioEditorError(path + "." + std::string(key) + " must be a string");
    }
    return scenario_yaml::copy_scalar(value.val());
}

RuleDefinition parse_rule(
    ConstNodeRef node,
    const AnchorMap& anchors,
    std::set<std::string>& expanding,
    const std::string& path
) {
    if (!node.is_map()) {
        throw ScenarioEditorError(path + " must be a rule mapping");
    }
    check_unique_keys(node, path);
    const auto condition = scenario_yaml::child(node, "condition");
    if (condition.invalid()) {
        throw ScenarioEditorError(path + ".condition is missing");
    }
    RuleDefinition rule;
    rule.condition = *condition_usage(condition, anchors, expanding, path + ".condition");
    rule.action = scalar_field(node, "action", path);
    return rule;
}

ScenarioRule parse_scenario_rule(
    ConstNodeRef node,
    const AnchorMap& anchors,
    std::set<std::string>& expanding,
    const std::string& path
) {
    if (!node.is_map()) {
        throw ScenarioEditorError(path + " must be a rule mapping");
    }
    check_unique_keys(node, path);
    const auto sequence = scenario_yaml::child(node, "sequence");
    if (!sequence.invalid()) {
        if (!sequence.is_seq()) {
            throw ScenarioEditorError(path + ".sequence must be a list");
        }
        ScenarioRule result;
        result.sequence = true;
        std::size_t index = 0;
        for (const auto item : sequence.children()) {
            result.sequence_rules.push_back(parse_rule(
                item,
                anchors,
                expanding,
                path + ".sequence[" + std::to_string(index++) + "]"
            ));
        }
        return result;
    }
    ScenarioRule result;
    result.rule = parse_rule(node, anchors, expanding, path);
    return result;
}

std::vector<std::optional<SplitDefinition>> parse_splits(
    ConstNodeRef node,
    const AnchorMap& anchors,
    std::set<std::string>& expanding
) {
    if (node.invalid() || !node.is_seq()) {
        throw ScenarioEditorError("scenario.splits must be a list");
    }
    std::vector<std::optional<SplitDefinition>> splits;
    std::size_t split_index = 0;
    for (const auto item : node.children()) {
        const std::string split_path = "splits[" + std::to_string(split_index++) + "]";
        if (scenario_yaml::is_null(item)) {
            splits.emplace_back(std::nullopt);
            continue;
        }
        if (!item.is_map()) {
            throw ScenarioEditorError(split_path + " must be a mapping or null");
        }
        check_unique_keys(item, split_path);
        const auto rules = scenario_yaml::child(item, "rules");
        if (rules.invalid() || !rules.is_seq()) {
            throw ScenarioEditorError(split_path + ".rules must be a list");
        }
        SplitDefinition split;
        std::size_t rule_index = 0;
        for (const auto rule : rules.children()) {
            split.rules.push_back(parse_scenario_rule(
                rule,
                anchors,
                expanding,
                split_path + ".rules[" + std::to_string(rule_index++) + "]"
            ));
        }
        splits.emplace_back(std::move(split));
    }
    return splits;
}

void add_definition(
    ScenarioDocument& document,
    std::map<std::string, ryml::id_type>& definition_nodes,
    std::string name,
    ryml::id_type node_id,
    Value value
) {
    if (name.empty()) {
        throw ScenarioEditorError("shared definition names must not be empty");
    }
    const auto existing = definition_nodes.find(name);
    if (existing != definition_nodes.end()) {
        if (existing->second == node_id) {
            return;
        }
        throw ScenarioEditorError("shared definition is duplicated: " + name);
    }
    definition_nodes.emplace(name, node_id);
    document.definitions.push_back(SharedDefinition{
        std::move(name), classify_definition(value), std::move(value)
    });
}

}  // namespace

ScenarioDocument import_scenario_yaml(std::string_view source, std::string source_name) {
    const auto callbacks = yaml_callbacks();
    ryml::Tree tree{callbacks};
    ryml::EventHandlerTree handler{callbacks};
    ryml::Parser parser{&handler};
    const std::string filename = std::move(source_name);
    ryml::parse_in_arena(
        &parser,
        ryml::csubstr{filename.data(), filename.size()},
        ryml::csubstr{source.data(), source.size()},
        &tree
    );

    ConstNodeRef root = tree.crootref();
    if (root.is_stream()) {
        if (root.num_children() == 0) {
            throw ScenarioEditorError("scenario must be a mapping");
        }
        root = root.first_child();
    }
    if (root.invalid() || !root.is_map()) {
        throw ScenarioEditorError("scenario must be a mapping");
    }
    check_unique_keys(root, "scenario");

    AnchorMap anchors;
    collect_anchors(root, anchors);
    std::set<ryml::id_type> structural_ids;
    collect_structural_ids(root, structural_ids);
    for (const auto& [name, node] : anchors) {
        if (structural_ids.contains(node.id())) {
            yaml_error("anchor '" + name + "' is attached to an unsupported scenario structure");
        }
    }

    std::set<std::string> expanding;
    ScenarioDocument document;
    std::map<std::string, ryml::id_type> definition_nodes;

    if (const auto definitions = scenario_yaml::child(root, "definitions");
        !definitions.invalid()) {
        if (!definitions.is_map()) {
            throw ScenarioEditorError("definitions must be a mapping");
        }
        check_unique_keys(definitions, "definitions");
        for (const auto entry : definitions.children()) {
            if (!entry.has_key() || entry.key_is_null()) {
                throw ScenarioEditorError("definitions keys must be strings");
            }
            const std::string key = scenario_yaml::copy_scalar(entry.key());
            const auto anchor = node_anchor(entry);
            const std::string name = anchor.value_or(key);
            add_definition(
                document,
                definition_nodes,
                name,
                entry.id(),
                value_from_node(
                    entry,
                    anchors,
                    expanding,
                    "definitions." + key,
                    anchor ? std::optional<ryml::id_type>{entry.id()} : std::nullopt
                )
            );
        }
    }

    const std::set<std::string> scenario_fields{
        "definitions",
        "start_condition",
        "reset_condition",
        "incomplete_condition",
        "splits",
    };
    for (const auto entry : root.children()) {
        if (!entry.has_key() || entry.key_is_null()) {
            continue;
        }
        const std::string key = scenario_yaml::copy_scalar(entry.key());
        if (scenario_fields.contains(key)) {
            continue;
        }
        const auto anchor = node_anchor(entry);
        if (!anchor) {
            continue;
        }
        add_definition(
            document,
            definition_nodes,
            *anchor,
            entry.id(),
            value_from_node(
                entry,
                anchors,
                expanding,
                key,
                std::optional<ryml::id_type>{entry.id()}
            )
        );
    }

    for (const auto& [name, node] : anchors) {
        if (const auto existing = definition_nodes.find(name); existing != definition_nodes.end()) {
            if (existing->second == node.id()) {
                continue;
            }
            throw ScenarioEditorError("shared definition is duplicated: " + name);
        }
        add_definition(
            document,
            definition_nodes,
            name,
            node.id(),
            value_from_node(
                node,
                anchors,
                expanding,
                name,
                std::optional<ryml::id_type>{node.id()}
            )
        );
    }

    document.start_condition = condition_usage(
        scenario_yaml::child(root, "start_condition"), anchors, expanding, "start_condition"
    );
    document.reset_condition = condition_usage(
        scenario_yaml::child(root, "reset_condition"), anchors, expanding, "reset_condition"
    );
    document.incomplete_condition = condition_usage(
        scenario_yaml::child(root, "incomplete_condition"), anchors, expanding, "incomplete_condition"
    );
    document.splits = parse_splits(
        scenario_yaml::child(root, "splits"), anchors, expanding
    );

    validate_scenario_document(document);
    return document;
}

ScenarioDocument load_scenario_document(const std::filesystem::path& path) {
    std::ifstream stream{path, std::ios::binary};
    if (!stream) {
        throw ScenarioEditorError("could not open scenario file: " + path_to_utf8(path));
    }
    const std::string source{
        std::istreambuf_iterator<char>{stream},
        std::istreambuf_iterator<char>{},
    };
    if (stream.bad()) {
        throw ScenarioEditorError("could not read scenario file: " + path_to_utf8(path));
    }
    return import_scenario_yaml(source, path_to_utf8(path));
}

}  // namespace divergencesplitter::scenario_editor
