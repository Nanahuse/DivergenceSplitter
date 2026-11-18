#include "divergencesplitter/scenario/editor/document.hpp"

#include <algorithm>
#include <cctype>
#include <locale>
#include <set>
#include <sstream>
#include <string_view>

namespace divergencesplitter::scenario_editor {
namespace {

bool yaml_ambiguous_string(std::string_view text) {
    if (text.empty()) {
        return true;
    }
    std::string lowered{text};
    std::transform(lowered.begin(), lowered.end(), lowered.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    static const std::set<std::string> ambiguous{
        "~", "null", "true", "false", "yes", "no", "on", "off",
        ".nan", ".inf", "-.inf", "+.inf",
    };
    if (ambiguous.contains(lowered)) {
        return true;
    }
    std::istringstream stream{std::string{text}};
    stream.imbue(std::locale::classic());
    stream.unsetf(std::ios::dec);
    double number{};
    if ((stream >> std::noskipws >> number) && (stream >> std::ws).eof()) {
        return true;
    }
    return false;
}

}  // namespace

nlohmann::json value_to_json(const Value& value) {
    switch (value.kind) {
    case ValueKind::null_value:
        return nullptr;
    case ValueKind::scalar:
        return value.scalar;
    case ValueKind::alias:
        return nlohmann::json{{"$alias", value.scalar}};
    case ValueKind::parameter_reference:
        return nlohmann::json{{"$param", value.scalar}};
    case ValueKind::sequence: {
        nlohmann::json result = nlohmann::json::array();
        for (const auto& item : value.sequence) {
            result.push_back(value_to_json(item));
        }
        return result;
    }
    case ValueKind::mapping: {
        nlohmann::json result = nlohmann::json::object();
        for (const auto& [key, item] : value.mapping) {
            result[key] = value_to_json(item);
        }
        return result;
    }
    }
    return nullptr;
}

Value value_from_json(const nlohmann::json& value) {
    if (value.is_null()) {
        return Value::make_null();
    }
    if (value.is_string()) {
        Value result = Value::make_scalar(value.get<std::string>());
        result.quoted = yaml_ambiguous_string(result.scalar);
        return result;
    }
    if (value.is_boolean()) {
        return Value::make_scalar(value.get<bool>() ? "true" : "false");
    }
    if (value.is_number()) {
        return Value::make_scalar(value.dump());
    }
    if (value.is_array()) {
        Value result = Value::make_sequence();
        result.sequence.reserve(value.size());
        for (const auto& item : value) {
            result.sequence.push_back(value_from_json(item));
        }
        return result;
    }
    if (value.is_object()) {
        if (value.size() == 1 && value.contains("$param") && value["$param"].is_string()) {
            return Value::make_parameter_reference(value["$param"].get<std::string>());
        }
        if (value.size() == 1 && value.contains("$alias") && value["$alias"].is_string()) {
            return Value::make_alias(value["$alias"].get<std::string>());
        }
        Value result = Value::make_mapping();
        for (const auto& [key, item] : value.items()) {
            result.mapping.emplace_back(key, value_from_json(item));
        }
        return result;
    }
    throw ScenarioEditorError("unsupported JSON value");
}

}  // namespace divergencesplitter::scenario_editor
