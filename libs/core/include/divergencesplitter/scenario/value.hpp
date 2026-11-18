#pragma once

#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace divergencesplitter::scenario {

enum class ValueKind {
    null_value,
    scalar,
    alias,
    parameter_reference,
    sequence,
    mapping,
};

struct Value {
    ValueKind kind{ValueKind::null_value};
    std::string scalar;
    bool quoted{false};
    std::vector<Value> sequence;
    std::vector<std::pair<std::string, Value>> mapping;

    [[nodiscard]] static Value make_null();
    [[nodiscard]] static Value make_scalar(std::string value);
    [[nodiscard]] static Value make_alias(std::string anchor);
    [[nodiscard]] static Value make_parameter_reference(std::string parameter);
    [[nodiscard]] static Value make_sequence(std::vector<Value> items = {});
    [[nodiscard]] static Value make_mapping(
        std::vector<std::pair<std::string, Value>> entries = {}
    );

    [[nodiscard]] bool is_null() const noexcept { return kind == ValueKind::null_value; }
    [[nodiscard]] bool is_scalar() const noexcept { return kind == ValueKind::scalar; }
    [[nodiscard]] bool is_alias() const noexcept { return kind == ValueKind::alias; }
    [[nodiscard]] bool is_parameter_reference() const noexcept {
        return kind == ValueKind::parameter_reference;
    }
    [[nodiscard]] bool is_sequence() const noexcept { return kind == ValueKind::sequence; }
    [[nodiscard]] bool is_mapping() const noexcept { return kind == ValueKind::mapping; }

    [[nodiscard]] const Value* find(std::string_view key) const;
    [[nodiscard]] Value* find(std::string_view key);
    [[nodiscard]] const Value* find_index(std::size_t index) const;
    [[nodiscard]] Value* find_index(std::size_t index);

    // Appends the key or replaces the existing value while retaining its position.
    void set(std::string key, Value value);
    bool erase(std::string_view key);
};

}  // namespace divergencesplitter::scenario
