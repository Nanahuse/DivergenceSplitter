#pragma once

#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "divergencesplitter/scenario/value.hpp"

namespace divergencesplitter::scenario::v2 {

struct ParameterDefinition {
    std::string name;
    Value default_value;
};

struct SharedCondition {
    std::string name;
    std::vector<ParameterDefinition> parameters;
    Value condition;
};

struct SharedDetector {
    std::string name;
    std::vector<ParameterDefinition> parameters;
    Value detector;
};

struct Definitions {
    std::vector<SharedCondition> conditions;
    std::vector<SharedDetector> detectors;
};

struct Document {
    Definitions definitions;
    Value start_condition;
    std::optional<Value> reset_condition;
    std::optional<Value> incomplete_condition;
    Value splits;
    std::vector<std::pair<std::string, Value>> extra_root;
};

[[nodiscard]] const SharedCondition* find_condition(
    const Definitions& definitions,
    std::string_view name
);
[[nodiscard]] SharedCondition* find_condition(Definitions& definitions, std::string_view name);
[[nodiscard]] const SharedDetector* find_detector(
    const Definitions& definitions,
    std::string_view name
);
[[nodiscard]] SharedDetector* find_detector(Definitions& definitions, std::string_view name);

// Parses the v2 root value. `schema_version` must be 2.
[[nodiscard]] Document parse_document(const Value& root);

// Resolves shared definitions and parameter references. The returned condition
// or detector contains no `use`, `with`, or parameter references.
[[nodiscard]] Value resolve_condition(const Definitions& definitions, const Value& usage);
[[nodiscard]] Value resolve_detector(const Definitions& definitions, const Value& usage);

// Resolves the whole scenario into the legacy normalized shape consumed by the
// existing runtime parser.
[[nodiscard]] Value normalize_scenario(const Document& document);

void validate_document(const Document& document);

}  // namespace divergencesplitter::scenario::v2
