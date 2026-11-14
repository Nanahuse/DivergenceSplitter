#include "divergencesplitter/scenario/editor/model.hpp"

#include <cmath>
#include <locale>
#include <regex>
#include <set>
#include <sstream>
#include <string>
#include <string_view>

namespace divergencesplitter::scenario_editor {
namespace {

Value scalar(std::string value) {
    return Value::make_scalar(std::move(value));
}

Value elapsed_condition() {
    return Value::make_mapping({
        {"type", scalar("elapsed")},
        {"duration", scalar("1s")},
    });
}

Value condition_list_default() {
    return Value::make_sequence({elapsed_condition()});
}

Value mean_brightness_detector() {
    return Value::make_mapping({{"type", scalar("mean_brightness")}});
}

Value roi_default() {
    return Value::make_mapping({
        {"x", scalar("0")},
        {"y", scalar("0")},
        {"width", scalar("1")},
        {"height", scalar("1")},
    });
}

FieldSchema field(
    std::string name,
    FieldKind kind,
    bool required,
    Value default_value = Value::make_null()
) {
    return FieldSchema{std::move(name), kind, required, std::move(default_value)};
}

FieldSchema reference_field() {
    return field("reference", FieldKind::text, true, scalar("reference.png"));
}

FieldSchema roi_field() {
    return field("roi", FieldKind::roi, false, roi_default());
}

EditorSchema make_schema() {
    EditorSchema schema;

    schema.condition_fields["detected"] = {
        field("minimum_score", FieldKind::number, true, scalar("0.9")),
        field("detector", FieldKind::detector, true, mean_brightness_detector()),
    };
    schema.condition_fields["all"] = {
        field("conditions", FieldKind::condition_list, true, condition_list_default()),
    };
    schema.condition_fields["any"] = {
        field("conditions", FieldKind::condition_list, true, condition_list_default()),
    };
    schema.condition_fields["not"] = {
        field("condition", FieldKind::condition, true, elapsed_condition()),
    };
    schema.condition_fields["rising_edge"] = {
        field("condition", FieldKind::condition, true, elapsed_condition()),
    };
    schema.condition_fields["falling_edge"] = {
        field("condition", FieldKind::condition, true, elapsed_condition()),
    };
    schema.condition_fields["once"] = {
        field("condition", FieldKind::condition, true, elapsed_condition()),
    };
    schema.condition_fields["elapsed"] = {
        field("duration", FieldKind::duration, true, scalar("1s")),
    };
    schema.condition_fields["hold"] = {
        field("condition", FieldKind::condition, true, elapsed_condition()),
        field("duration", FieldKind::duration, true, scalar("1s")),
    };
    schema.condition_fields["nth"] = {
        field("condition", FieldKind::condition, true, elapsed_condition()),
        field("count", FieldKind::integer, true, scalar("1")),
    };
    schema.condition_fields["reset_when"] = {
        field("condition", FieldKind::condition, true, elapsed_condition()),
        field("reset_condition", FieldKind::condition, true, elapsed_condition()),
    };
    schema.condition_fields["then"] = {
        field("conditions", FieldKind::condition_list, true, condition_list_default()),
        field("within", FieldKind::duration, false, scalar("1s")),
    };

    const auto image_detector = [&]() {
        return std::vector<FieldSchema>{
            reference_field(),
            roi_field(),
        };
    };
    schema.detector_fields["template_match"] = image_detector();
    schema.detector_fields["mean_absolute_similarity"] = image_detector();
    schema.detector_fields["root_mean_square_similarity"] = image_detector();
    schema.detector_fields["histogram_similarity"] = image_detector();
    schema.detector_fields["perceptual_hash_similarity"] = image_detector();
    schema.detector_fields["phase_correlation"] = image_detector();
    schema.detector_fields["difference_hash_similarity"] = {
        reference_field(),
        field("hash_size", FieldKind::integer, false, scalar("8")),
        roi_field(),
    };
    schema.detector_fields["mean_brightness"] = {
        roi_field(),
    };
    schema.detector_fields["color_range"] = {
        field(
            "lower",
            FieldKind::number_list,
            true,
            Value::make_sequence({scalar("0"), scalar("0"), scalar("0")})
        ),
        field(
            "upper",
            FieldKind::number_list,
            true,
            Value::make_sequence({scalar("255"), scalar("255"), scalar("255")})
        ),
        roi_field(),
    };

    return schema;
}

const std::vector<FieldSchema>& fields_for(
    const std::map<std::string, std::vector<FieldSchema>>& fields,
    const std::string& type,
    std::string_view kind
) {
    const auto found = fields.find(type);
    if (found == fields.end()) {
        throw ScenarioEditorError(
            "unsupported " + std::string(kind) + " type: " + type
        );
    }
    return found->second;
}

double parse_number(std::string_view text, std::string_view field_name) {
    std::istringstream stream{std::string{text}};
    stream.imbue(std::locale::classic());
    stream.unsetf(std::ios::dec);
    double value{};
    if (!(stream >> std::noskipws >> value) || !(stream >> std::ws).eof()
        || !std::isfinite(value)) {
        throw ScenarioEditorError(std::string(field_name) + " must be a number");
    }
    return value;
}

long long parse_integer(std::string_view text, std::string_view field_name) {
    std::istringstream stream{std::string{text}};
    stream.imbue(std::locale::classic());
    stream.unsetf(std::ios::dec);
    long long value{};
    if (!(stream >> std::noskipws >> value) || !(stream >> std::ws).eof()) {
        throw ScenarioEditorError(std::string(field_name) + " must be an integer");
    }
    return value;
}

void validate_duration(std::string_view text, std::string_view field_name) {
    static const std::regex pattern{R"(^(\d+(?:\.\d+)?)(ms|s)$)"};
    if (!std::regex_match(text.begin(), text.end(), pattern)) {
        throw ScenarioEditorError(
            std::string(field_name) + " must be a duration like '500ms' or '3s'"
        );
    }
}

void validate_roi(const Value& value, const std::string& field_name) {
    static const std::set<std::string_view> roi_keys{"x", "y", "width", "height"};
    if (!value.is_mapping()) {
        throw ScenarioEditorError(field_name + " must be a mapping");
    }
    for (const auto& [key, item] : value.mapping) {
        (void)item;
        if (!roi_keys.contains(key)) {
            throw ScenarioEditorError(field_name + "." + key + " is an unknown ROI field");
        }
    }
    const auto coordinate = [&](std::string_view key) {
        const auto* item = value.find(key);
        if (item == nullptr || !item->is_scalar()) {
            throw ScenarioEditorError(field_name + "." + std::string(key) + " is required");
        }
        return parse_integer(item->scalar, field_name + "." + std::string(key));
    };
    const auto x = coordinate("x");
    const auto y = coordinate("y");
    const auto width = coordinate("width");
    const auto height = coordinate("height");
    if (x < 0 || y < 0 || width <= 0 || height <= 0) {
        throw ScenarioEditorError(
            field_name + " must be non-negative with positive dimensions"
        );
    }
}

void validate_number_list(const Value& value, const std::string& field_name) {
    if (!value.is_sequence()) {
        throw ScenarioEditorError(field_name + " must be a list");
    }
    for (const auto& item : value.sequence) {
        if (!item.is_scalar()) {
            throw ScenarioEditorError(field_name + " values must be numbers");
        }
        (void)parse_number(item.scalar, field_name);
    }
}

void validate_field_value(const FieldSchema& field_schema, const Value& value) {
    if (value.is_null()) {
        throw ScenarioEditorError(field_schema.name + " must not be null");
    }
    switch (field_schema.kind) {
    case FieldKind::text:
        if (!value.is_scalar()) {
            throw ScenarioEditorError(field_schema.name + " must be a string");
        }
        break;
    case FieldKind::number:
        if (!value.is_scalar()) {
            throw ScenarioEditorError(field_schema.name + " must be a number");
        }
        (void)parse_number(value.scalar, field_schema.name);
        break;
    case FieldKind::integer:
        if (!value.is_scalar()) {
            throw ScenarioEditorError(field_schema.name + " must be an integer");
        }
        (void)parse_integer(value.scalar, field_schema.name);
        break;
    case FieldKind::duration:
        if (!value.is_scalar()) {
            throw ScenarioEditorError(field_schema.name + " must be a duration");
        }
        validate_duration(value.scalar, field_schema.name);
        break;
    case FieldKind::condition:
        validate_condition_schema(value);
        break;
    case FieldKind::condition_list:
        if (!value.is_sequence()) {
            throw ScenarioEditorError(field_schema.name + " must be a list");
        }
        for (const auto& item : value.sequence) {
            validate_condition_schema(item);
        }
        break;
    case FieldKind::detector:
        validate_detector_schema(value);
        break;
    case FieldKind::roi:
        validate_roi(value, field_schema.name);
        break;
    case FieldKind::number_list:
        validate_number_list(value, field_schema.name);
        break;
    }
}

void validate_typed_mapping(
    const Value& value,
    const std::map<std::string, std::vector<FieldSchema>>& fields,
    std::string_view kind
) {
    if (!value.is_mapping()) {
        throw ScenarioEditorError(std::string(kind) + " must be a mapping");
    }
    const auto* type = value.find("type");
    if (type == nullptr || !type->is_scalar() || type->scalar.empty()) {
        throw ScenarioEditorError(std::string(kind) + ".type must be a string");
    }
    const auto& schema_fields = fields_for(fields, type->scalar, kind);

    std::map<std::string, const FieldSchema*> by_name;
    for (const auto& field_schema : schema_fields) {
        by_name.emplace(field_schema.name, &field_schema);
    }
    for (const auto& [key, item] : value.mapping) {
        (void)item;
        if (key == "type" || (kind == "condition" && key == "id")) {
            continue;
        }
        if (!by_name.contains(key)) {
            throw ScenarioEditorError(
                "unknown " + std::string(kind) + " field for " + type->scalar + ": " + key
            );
        }
    }
    if (const auto* id = value.find("id");
        kind == "condition" && id != nullptr
        && (!id->is_scalar() || id->scalar.empty())) {
        throw ScenarioEditorError("condition ids must be non-empty strings");
    }
    for (const auto& field_schema : schema_fields) {
        const auto* item = value.find(field_schema.name);
        if (item == nullptr) {
            if (field_schema.required) {
                throw ScenarioEditorError(
                    type->scalar + "." + field_schema.name + " is required"
                );
            }
            continue;
        }
        validate_field_value(field_schema, *item);
    }
}

}  // namespace

const EditorSchema& editor_schema() {
    static const EditorSchema schema = make_schema();
    return schema;
}

void validate_condition_schema(const Value& value) {
    validate_typed_mapping(value, editor_schema().condition_fields, "condition");
}

void validate_detector_schema(const Value& value) {
    validate_typed_mapping(value, editor_schema().detector_fields, "detector");
}

}  // namespace divergencesplitter::scenario_editor
