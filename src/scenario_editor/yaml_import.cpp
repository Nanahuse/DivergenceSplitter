#include "divergencesplitter/scenario/editor/document.hpp"

#include <ryml/ryml.hpp>
#include <ryml/ryml_std.hpp>

#include <algorithm>
#include <fstream>
#include <map>
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

void collect_anchors(ConstNodeRef node, AnchorMap& anchors) {
    if (node.has_val_anchor()) {
        const std::string name = scenario_yaml::copy_scalar(node.val_anchor());
        if (!name.empty()) {
            anchors[name] = node;
        }
    }
    for (const auto child : node.children()) {
        collect_anchors(child, anchors);
    }
}

Value value_from_node(
    ConstNodeRef node,
    const AnchorMap& anchors,
    std::set<std::string>& expanding,
    const std::string& path
);

Value value_from_map(
    ConstNodeRef node,
    const AnchorMap& anchors,
    std::set<std::string>& expanding,
    const std::string& path
) {
    Value result = Value::make_mapping();
    for (const auto entry : node.children()) {
        if (!entry.has_key() || entry.key_is_null()) {
            yaml_error(path + " mapping keys must be strings");
        }
        const std::string key = scenario_yaml::copy_scalar(entry.key());
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
                Value merged = value_from_node(target->second, anchors, expanding, path + ".<<");
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
        result.set(key, value_from_node(entry, anchors, expanding, path + "." + key));
    }
    return result;
}

Value value_from_node(
    ConstNodeRef node,
    const AnchorMap& anchors,
    std::set<std::string>& expanding,
    const std::string& path
) {
    if (node.is_val_ref()) {
        return Value::make_alias(scenario_yaml::copy_scalar(node.val_ref()));
    }
    if (node.is_map()) {
        return value_from_map(node, anchors, expanding, path);
    }
    if (node.is_seq()) {
        Value result = Value::make_sequence();
        std::size_t index = 0;
        for (const auto item : node.children()) {
            result.sequence.push_back(value_from_node(
                item, anchors, expanding, path + "[" + std::to_string(index++) + "]"
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
    std::vector<SharedDefinition>& definitions,
    std::set<std::string>& names,
    std::string name,
    Value value
) {
    if (name.empty()) {
        throw ScenarioEditorError("shared definition names must not be empty");
    }
    if (!names.insert(name).second) {
        return;
    }
    definitions.push_back(SharedDefinition{std::move(name), classify_definition(value), std::move(value)});
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

    AnchorMap anchors;
    collect_anchors(root, anchors);

    std::set<std::string> expanding;
    ScenarioDocument document;
    std::set<std::string> definition_names;

    if (const auto definitions = scenario_yaml::child(root, "definitions"); !definitions.invalid()) {
        if (!definitions.is_map()) {
            throw ScenarioEditorError("definitions must be a mapping");
        }
        for (const auto entry : definitions.children()) {
            if (!entry.has_key() || entry.key_is_null()) {
                throw ScenarioEditorError("definitions keys must be strings");
            }
            std::string name = scenario_yaml::copy_scalar(entry.key());
            if (entry.has_val_anchor()) {
                name = scenario_yaml::copy_scalar(entry.val_anchor());
            }
            add_definition(
                document.definitions,
                definition_names,
                std::move(name),
                value_from_node(entry, anchors, expanding, "definitions." + scenario_yaml::copy_scalar(entry.key()))
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
        if (scenario_fields.contains(key) || !entry.has_val_anchor() || !entry.is_map()) {
            continue;
        }
        add_definition(
            document.definitions,
            definition_names,
            scenario_yaml::copy_scalar(entry.val_anchor()),
            value_from_node(entry, anchors, expanding, key)
        );
    }

    // Nested anchors may be referenced from unrelated Condition positions.
    // Exporting them under `definitions` keeps those aliases resolvable.
    for (const auto& [name, node] : anchors) {
        if (definition_names.contains(name) || !node.is_map()) {
            continue;
        }
        auto value = value_from_node(node, anchors, expanding, name);
        if (value.is_mapping() && value.find("type") != nullptr) {
            add_definition(document.definitions, definition_names, name, std::move(value));
        }
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
