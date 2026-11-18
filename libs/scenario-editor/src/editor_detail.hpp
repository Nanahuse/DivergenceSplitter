#pragma once

#include "divergencesplitter/scenario/editor/document.hpp"

#include <cstddef>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

namespace divergencesplitter::scenario_editor::detail {

struct PathToken {
    bool is_index{false};
    std::size_t index{};
    std::string key;
};

using Path = std::vector<PathToken>;

enum class DefinitionKind {
    condition,
    detector,
};

struct DefinitionRef {
    DefinitionKind kind{DefinitionKind::condition};
    std::string name;
    Value* root{};
    std::vector<scenario::v2::ParameterDefinition>* parameters{};
};

Value* traverse(Value* value, const Path& path, std::size_t from);
const Value* value_at_path(const Value& root, const Path& path);
bool is_usage_value(const Value& value);
std::string_view definition_kind_name(DefinitionKind kind);
DefinitionKind expected_kind_for_key(std::string_view key, DefinitionKind current);
std::optional<DefinitionRef> find_use_definition(
    ScenarioDocument& document,
    const Value& usage,
    DefinitionKind expected
);
void mutate_document(ScenarioDocument& document, const nlohmann::json& command);

}  // namespace divergencesplitter::scenario_editor::detail
