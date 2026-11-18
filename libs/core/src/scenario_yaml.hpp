#pragma once

#include <set>
#include <string>
#include <string_view>

#include <ryml/ryml.hpp>

#include "divergencesplitter/scenario/scenario.hpp"

namespace divergencesplitter::scenario_yaml {

using StringSet = std::set<std::string>;
inline const StringSet roi_fields{"x", "y", "width", "height"};

[[noreturn]] inline void schema_error(const std::string& message) {
    throw ScenarioLoadError(ScenarioErrorKind::schema, message);
}

// Missing children are represented by an invalid reference, never a seeded node.
inline ryml::ConstNodeRef child(ryml::ConstNodeRef node, std::string_view key) {
    if (node.invalid() || !node.is_map()) {
        return {};
    }
    return node.find_child(ryml::csubstr{key.data(), key.size()});
}

inline bool is_null(ryml::ConstNodeRef node) {
    if (node.invalid() || !node.has_val()) {
        return false;
    }
    if (node.has_val_tag()) {
        if (node.val_tag() == "!!str" || node.val_tag() == "tag:yaml.org,2002:str") {
            return false;
        }
        if (node.val_tag() == "!!null" || node.val_tag() == "tag:yaml.org,2002:null") {
            return true;
        }
    }
    return node.val_is_null();
}

inline std::string copy_scalar(ryml::csubstr value) {
    return value.len ? std::string{value.str, value.len} : std::string{};
}

inline std::string unique_key(ryml::ConstNodeRef entry, std::string_view path, StringSet& keys) {
    if (!entry.has_key() || entry.key_is_null()) {
        schema_error(std::string(path) + " mapping keys must be strings");
    }
    const auto key = copy_scalar(entry.key());
    if (!keys.insert(key).second) {
        schema_error(std::string(path) + "." + key + " is duplicated");
    }
    return key;
}

}  // namespace divergencesplitter::scenario_yaml
