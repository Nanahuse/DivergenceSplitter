#include "divergencesplitter/scenario/editor/document.hpp"

#include <ryml/ryml.hpp>
#include <ryml/ryml_std.hpp>

#include <fstream>
#include <map>
#include <optional>
#include <set>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "../core/scenario_yaml.hpp"
#include "divergencesplitter/scenario/yaml_value.hpp"

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

void validate_and_resolve_yaml(ryml::Tree& tree, ConstNodeRef root) {
    std::map<std::string, ConstNodeRef> anchors;
    const auto target_for = [&](ConstNodeRef node, ryml::csubstr name) {
        const auto found = anchors.find(scenario_yaml::copy_scalar(name));
        if (found == anchors.end()) {
            yaml_error("anchor not found: " + scenario_yaml::copy_scalar(name));
        }
        const auto value = found->second;
        if (!value.invalid()
            && (value.id() == node.id()
                || node.tree()->is_ancestor(node.id(), value.id()))) {
            yaml_error("cyclic alias: " + scenario_yaml::copy_scalar(name));
        }
        return value;
    };

    const auto visit = [&](auto&& self, ConstNodeRef node) -> void {
        if (node.is_key_ref()) {
            const auto value = target_for(node, node.key_ref());
            if (!value.invalid() && value.is_container()) {
                yaml_error("mapping keys must be strings");
            }
        }
        if (node.is_val_ref()) {
            const auto value = target_for(node, node.val_ref());
            const auto parent = node.parent();
            const bool merge = (node.has_key() && node.key() == "<<")
                || (!parent.invalid() && parent.is_seq() && parent.has_key()
                    && parent.key() == "<<");
            if (merge && (value.invalid() || !value.is_map())) {
                yaml_error("merge aliases must refer to mappings");
            }
        }
        if (node.has_key_anchor()) {
            anchors[scenario_yaml::copy_scalar(node.key_anchor())] = {};
        }
        if (node.has_val_anchor()) {
            anchors[scenario_yaml::copy_scalar(node.val_anchor())] = node;
        }
        if (node.has_key() && node.key() == "<<") {
            if (node.is_seq()) {
                for (const auto item : node.children()) {
                    if (!item.is_val_ref()) {
                        yaml_error("merge sequences must contain mapping aliases");
                    }
                }
            } else if (!node.is_val_ref() && node.is_container()) {
                yaml_error("merge values must be mapping aliases or lists of mapping aliases");
            }
        }
        std::set<std::string> keys;
        for (const auto item : node.children()) {
            if (node.is_map() && !item.is_key_ref()) {
                if (item.key_is_null()) {
                    yaml_error("mapping keys must be strings");
                }
                const std::string key = scenario_yaml::copy_scalar(item.key());
                if (!keys.insert(key).second) {
                    yaml_error("duplicate scenario field: " + key);
                }
            }
            self(self, item);
        }
    };
    visit(visit, root);
    tree.resolve();
}

std::string scalar_field(const Value& value, std::string_view key, const std::string& path) {
    const auto* item = value.find(key);
    if (item == nullptr || !item->is_scalar()) {
        throw ScenarioEditorError(path + "." + std::string(key) + " must be a string");
    }
    return item->scalar;
}

RuleDefinition parse_rule(const Value& value, const std::string& path) {
    if (!value.is_mapping()) {
        throw ScenarioEditorError(path + " must be a rule mapping");
    }
    for (const auto& [key, item] : value.mapping) {
        (void)item;
        if (key != "condition" && key != "action") {
            throw ScenarioEditorError(path + "." + key + " is an unknown rule field");
        }
    }
    const auto* condition = value.find("condition");
    if (condition == nullptr) {
        throw ScenarioEditorError(path + ".condition is missing");
    }
    RuleDefinition rule;
    rule.condition.value = *condition;
    rule.action = scalar_field(value, "action", path);
    return rule;
}

ScenarioRule parse_scenario_rule(const Value& value, const std::string& path) {
    if (!value.is_mapping()) {
        throw ScenarioEditorError(path + " must be a rule mapping");
    }
    const auto* sequence = value.find("sequence");
    if (sequence != nullptr) {
        if (value.mapping.size() != 1 || !sequence->is_sequence()) {
            throw ScenarioEditorError(path + ".sequence must be the only field and a list");
        }
        ScenarioRule result;
        result.sequence = true;
        std::size_t index = 0;
        for (const auto& step : sequence->sequence) {
            result.sequence_rules.push_back(parse_rule(
                step,
                path + ".sequence[" + std::to_string(index++) + "]"
            ));
        }
        return result;
    }
    ScenarioRule result;
    result.rule = parse_rule(value, path);
    return result;
}

std::vector<std::optional<SplitDefinition>> parse_splits(const Value& value) {
    if (!value.is_sequence()) {
        throw ScenarioEditorError("scenario.splits must be a list");
    }
    std::vector<std::optional<SplitDefinition>> splits;
    std::size_t split_index = 0;
    for (const auto& split : value.sequence) {
        const std::string split_path = "splits[" + std::to_string(split_index++) + "]";
        if (split.is_null()) {
            splits.emplace_back(std::nullopt);
            continue;
        }
        if (!split.is_mapping()) {
            throw ScenarioEditorError(split_path + " must be a mapping or null");
        }
        for (const auto& [key, item] : split.mapping) {
            (void)item;
            if (key != "rules") {
                throw ScenarioEditorError(split_path + "." + key + " is an unknown split field");
            }
        }
        const auto* rules = split.find("rules");
        if (rules == nullptr || !rules->is_sequence()) {
            throw ScenarioEditorError(split_path + ".rules must be a list");
        }
        SplitDefinition definition;
        std::size_t rule_index = 0;
        for (const auto& rule : rules->sequence) {
            definition.rules.push_back(parse_scenario_rule(
                rule,
                split_path + ".rules[" + std::to_string(rule_index++) + "]"
            ));
        }
        splits.emplace_back(std::move(definition));
    }
    return splits;
}

ScenarioDocument document_from_v2(scenario::v2::Document source) {
    ScenarioDocument document;
    document.definitions = std::move(source.definitions);
    document.start_condition = ConditionUsage{std::move(source.start_condition)};
    if (source.reset_condition) {
        document.reset_condition = ConditionUsage{std::move(*source.reset_condition)};
    }
    if (source.incomplete_condition) {
        document.incomplete_condition = ConditionUsage{std::move(*source.incomplete_condition)};
    }
    document.splits = parse_splits(source.splits);
    document.extra_root = std::move(source.extra_root);
    validate_scenario_document(document);
    return document;
}

}  // namespace

ScenarioDocument import_scenario_yaml(std::string_view source, std::string source_name) {
    const auto callbacks = yaml_callbacks();
    ryml::Tree tree{callbacks};
    ryml::EventHandlerTree handler{callbacks};
    ryml::Parser parser{&handler};
    const std::string filename = std::move(source_name);
    std::string_view text = source;
    if (text.size() >= 3
        && static_cast<unsigned char>(text[0]) == 0xEF
        && static_cast<unsigned char>(text[1]) == 0xBB
        && static_cast<unsigned char>(text[2]) == 0xBF) {
        text.remove_prefix(3);
    }
    ryml::parse_in_arena(
        &parser,
        ryml::csubstr{filename.data(), filename.size()},
        ryml::csubstr{text.data(), text.size()},
        &tree
    );

    ConstNodeRef root = tree.crootref();
    if (root.is_stream()) {
        if (root.num_children() == 0) {
            throw ScenarioEditorError("scenario must be a mapping");
        }
        root = root.first_child();
        while (!root.next_sibling().invalid()) {
            tree.remove(root.next_sibling().id());
        }
    }
    if (root.invalid() || !root.is_map()) {
        throw ScenarioEditorError("scenario must be a mapping");
    }
    validate_and_resolve_yaml(tree, root);

    const Value value = scenario::value_from_yaml(root);
    if (value.find("schema_version") == nullptr) {
        throw ScenarioEditorError(
            "Scenario Builder requires YAML v2 (schema_version: 2). "
            "Legacy YAML remains supported by DivergenceSplitter, but legacy import "
            "into the builder is not implemented yet."
        );
    }
    return document_from_v2(scenario::v2::parse_document(value));
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
