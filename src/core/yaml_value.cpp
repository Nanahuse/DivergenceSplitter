#include "divergencesplitter/scenario/yaml_value.hpp"

#include <ryml/ryml_std.hpp>

#include <set>
#include <stdexcept>
#include <string>
#include <string_view>

#include "scenario_yaml.hpp"

namespace divergencesplitter::scenario {
namespace {

[[noreturn]] void value_error(const std::string& message) {
    throw std::runtime_error(message);
}

bool explicit_string_tag(ryml::ConstNodeRef node) {
    if (!node.has_val_tag()) {
        return false;
    }
    const std::string tag = scenario_yaml::copy_scalar(node.val_tag());
    return tag == "!!str" || tag == "tag:yaml.org,2002:str";
}

ryml::csubstr view(const std::string& value) {
    return ryml::csubstr{value.data(), value.size()};
}

ryml::NodeRef append_key(ryml::NodeRef parent, const std::string& key) {
    ryml::NodeRef child = parent.append_child();
    const ryml::csubstr stored_key = parent.tree()->copy_to_arena(view(key));
    child.set_key(stored_key);
    child.set_key_style(static_cast<ryml::type_bits>(ryml::scalar_style_choose_block(stored_key)));
    return child;
}

}  // namespace

Value value_from_yaml(ryml::ConstNodeRef node) {
    if (node.is_val_ref()) {
        value_error("YAML aliases must be resolved before scenario v2 conversion");
    }
    if (node.is_map()) {
        std::set<std::string> keys;
        for (const auto entry : node.children()) {
            if (!entry.has_key() || entry.key_is_null() || entry.is_key_ref()) {
                value_error("mapping keys must be strings");
            }
            if (!keys.insert(scenario_yaml::copy_scalar(entry.key())).second) {
                value_error("duplicate mapping key: " + scenario_yaml::copy_scalar(entry.key()));
            }
        }
        if (keys.size() == 1 && keys.contains("param")) {
            const auto parameter = scenario_yaml::child(node, "param");
            if (parameter.invalid() || !parameter.has_val() || scenario_yaml::is_null(parameter)) {
                value_error("param references must contain a parameter name");
            }
            return Value::make_parameter_reference(
                scenario_yaml::copy_scalar(parameter.val())
            );
        }
        Value result = Value::make_mapping();
        for (const auto entry : node.children()) {
            result.set(
                scenario_yaml::copy_scalar(entry.key()),
                value_from_yaml(entry)
            );
        }
        return result;
    }
    if (node.is_seq()) {
        Value result = Value::make_sequence();
        for (const auto item : node.children()) {
            result.sequence.push_back(value_from_yaml(item));
        }
        return result;
    }
    if (node.invalid() || scenario_yaml::is_null(node)) {
        return Value::make_null();
    }
    if (!node.has_val()) {
        value_error("unsupported YAML value");
    }
    Value result = Value::make_scalar(scenario_yaml::copy_scalar(node.val()));
    result.quoted = node.is_val_quoted() || explicit_string_tag(node);
    return result;
}

void write_yaml_value(ryml::NodeRef node, const Value& value) {
    switch (value.kind) {
    case ValueKind::null_value:
        node.set_val("null");
        break;
    case ValueKind::scalar:
        node.set_val(view(value.scalar));
        node.set_val_style(static_cast<ryml::type_bits>(
            value.quoted
                ? ryml::VAL_DQUO
                : ryml::scalar_style_choose_block(view(value.scalar))
        ));
        break;
    case ValueKind::alias:
        node.set_val_ref(view(value.scalar));
        break;
    case ValueKind::parameter_reference: {
        node.set_map();
        auto parameter = append_key(node, "param");
        parameter.set_val(view(value.scalar));
        parameter.set_val_style(static_cast<ryml::type_bits>(
            ryml::scalar_style_choose_block(view(value.scalar))
        ));
        break;
    }
    case ValueKind::sequence:
        node.set_seq();
        for (const auto& item : value.sequence) {
            write_yaml_value(node.append_child(), item);
        }
        break;
    case ValueKind::mapping:
        node.set_map();
        for (const auto& [key, item] : value.mapping) {
            write_yaml_value(append_key(node, key), item);
        }
        break;
    }
}

}  // namespace divergencesplitter::scenario
