#pragma once

#include <ryml/ryml.hpp>

#include "divergencesplitter/scenario/value.hpp"

namespace divergencesplitter::scenario {

// Converts a resolved YAML node tree into the shared edit/resolution value tree.
// Parameter-reference mappings (`param: name`) become ValueKind::parameter_reference.
[[nodiscard]] Value value_from_yaml(ryml::ConstNodeRef node);

// Writes a value tree into a ryml node. Keys are copied into the tree arena;
// scalar values are expected to outlive the emitted/parsed tree.
void write_yaml_value(ryml::NodeRef node, const Value& value);

}  // namespace divergencesplitter::scenario
