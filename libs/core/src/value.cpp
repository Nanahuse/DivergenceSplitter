#include "divergencesplitter/scenario/value.hpp"

#include <algorithm>
#include <utility>

namespace divergencesplitter::scenario {

Value Value::make_null() {
    return Value{};
}

Value Value::make_scalar(std::string value) {
    Value result;
    result.kind = ValueKind::scalar;
    result.scalar = std::move(value);
    return result;
}

Value Value::make_alias(std::string anchor) {
    Value result;
    result.kind = ValueKind::alias;
    result.scalar = std::move(anchor);
    return result;
}

Value Value::make_parameter_reference(std::string parameter) {
    Value result;
    result.kind = ValueKind::parameter_reference;
    result.scalar = std::move(parameter);
    return result;
}

Value Value::make_sequence(std::vector<Value> items) {
    Value result;
    result.kind = ValueKind::sequence;
    result.sequence = std::move(items);
    return result;
}

Value Value::make_mapping(std::vector<std::pair<std::string, Value>> entries) {
    Value result;
    result.kind = ValueKind::mapping;
    result.mapping = std::move(entries);
    return result;
}

const Value* Value::find(std::string_view key) const {
    if (!is_mapping()) {
        return nullptr;
    }
    const auto found = std::find_if(mapping.begin(), mapping.end(), [&](const auto& entry) {
        return entry.first == key;
    });
    return found == mapping.end() ? nullptr : &found->second;
}

Value* Value::find(std::string_view key) {
    return const_cast<Value*>(std::as_const(*this).find(key));
}

const Value* Value::find_index(std::size_t index) const {
    if (!is_sequence() || index >= sequence.size()) {
        return nullptr;
    }
    return &sequence[index];
}

Value* Value::find_index(std::size_t index) {
    return const_cast<Value*>(std::as_const(*this).find_index(index));
}

void Value::set(std::string key, Value value) {
    if (!is_mapping()) {
        *this = make_mapping();
    }
    const auto found = std::find_if(mapping.begin(), mapping.end(), [&](const auto& entry) {
        return entry.first == key;
    });
    if (found == mapping.end()) {
        mapping.emplace_back(std::move(key), std::move(value));
    } else {
        found->second = std::move(value);
    }
}

bool Value::erase(std::string_view key) {
    if (!is_mapping()) {
        return false;
    }
    const auto found = std::find_if(mapping.begin(), mapping.end(), [&](const auto& entry) {
        return entry.first == key;
    });
    if (found == mapping.end()) {
        return false;
    }
    mapping.erase(found);
    return true;
}

}  // namespace divergencesplitter::scenario
