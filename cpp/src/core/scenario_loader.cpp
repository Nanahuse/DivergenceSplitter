#include "divergencesplitter/scenario/scenario.hpp"

#include <opencv2/imgcodecs.hpp>

#include <yaml-cpp/yaml.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <regex>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"

namespace divergencesplitter {
namespace {

using StringSet = std::set<std::string>;

struct LoadContext {
    std::filesystem::path base_directory;
    std::optional<ReferenceResizeOptions> reference_resize;
};

std::string lower_extension(const std::filesystem::path& path) {
    std::string extension = path.extension().string();
    std::transform(extension.begin(), extension.end(), extension.begin(), [](unsigned char value) {
        return static_cast<char>(std::tolower(value));
    });
    return extension;
}

[[noreturn]] void schema_error(const std::string& message) {
    throw ScenarioLoadError(ScenarioErrorKind::schema, message);
}

YAML::Node require_map(const YAML::Node& node, std::string_view field) {
    if (!node.IsMap()) {
        schema_error(std::string(field) + " must be a mapping");
    }
    return node;
}

std::string as_string(const YAML::Node& node, std::string_view field) {
    if (!node.IsScalar()) {
        schema_error(std::string(field) + " must be a string");
    }
    return node.as<std::string>();
}

double as_number(const YAML::Node& node, std::string_view field) {
    if (!node.IsScalar()) {
        schema_error(std::string(field) + " must be a number");
    }
    try {
        return node.as<double>();
    } catch (const YAML::Exception&) {
        schema_error(std::string(field) + " must be a number");
    }
}

int as_integer(const YAML::Node& node, std::string_view field) {
    if (!node.IsScalar()) {
        schema_error(std::string(field) + " must be an integer");
    }
    try {
        return node.as<int>();
    } catch (const YAML::Exception&) {
        schema_error(std::string(field) + " must be an integer");
    }
}

std::vector<YAML::Node> as_list(const YAML::Node& node, std::string_view field) {
    if (!node.IsSequence()) {
        schema_error(std::string(field) + " must be a list");
    }
    std::vector<YAML::Node> result;
    result.reserve(node.size());
    for (const auto& item : node) {
        result.push_back(item);
    }
    return result;
}

void check_keys(
    const YAML::Node& node,
    const StringSet& required,
    const StringSet& optional = {},
    bool allow_unknown = false
) {
    StringSet present;
    for (const auto& entry : node) {
        if (!entry.first.IsScalar()) {
            schema_error("mapping keys must be strings");
        }
        present.insert(entry.first.as<std::string>());
    }
    for (const auto& key : required) {
        if (!present.contains(key)) {
            schema_error("missing scenario field: " + key);
        }
    }
    if (!allow_unknown) {
        for (const auto& key : present) {
            if (!required.contains(key) && !optional.contains(key)) {
                schema_error("unknown scenario field: " + key);
            }
        }
    }
}

std::chrono::nanoseconds parse_duration(const YAML::Node& node, std::string_view field) {
    static const std::regex pattern{R"(^(\d+(?:\.\d+)?)(ms|s)$)"};
    const std::string text = as_string(node, field);
    std::smatch match;
    if (!std::regex_match(text, match, pattern)) {
        schema_error(std::string(field) + " must be a duration like '500ms' or '3s'");
    }
    const double amount = std::stod(match[1].str());
    const std::string unit = match[2].str();
    const double nanoseconds = amount * (unit == "s" ? 1'000'000'000.0 : 1'000'000.0);
    if (!std::isfinite(nanoseconds) || nanoseconds < 0.0) {
        schema_error(std::string(field) + " duration is invalid");
    }
    return std::chrono::nanoseconds{static_cast<std::int64_t>(nanoseconds)};
}

std::optional<Region> parse_roi(const YAML::Node& node, std::string_view field) {
    if (!node || node.IsNull()) {
        return std::nullopt;
    }
    const auto mapping = require_map(node, field);
    check_keys(mapping, {"x", "y", "width", "height"});
    Region region{
        as_integer(mapping["x"], std::string(field) + ".x"),
        as_integer(mapping["y"], std::string(field) + ".y"),
        as_integer(mapping["width"], std::string(field) + ".width"),
        as_integer(mapping["height"], std::string(field) + ".height"),
    };
    if (!region.valid()) {
        schema_error(std::string(field) + " must be non-negative with positive dimensions");
    }
    return region;
}

cv::Mat read_reference(
    const YAML::Node& node,
    std::string_view field,
    const LoadContext& context,
    const std::optional<Region>& roi
) {
    std::filesystem::path path = as_string(node, field);
    if (path.is_relative()) {
        path = context.base_directory / path;
    }
    std::ifstream stream{path, std::ios::binary};
    if (!stream) {
        schema_error(std::string(field) + " could not be opened: " + path.string());
    }
    std::vector<unsigned char> bytes(
        (std::istreambuf_iterator<char>(stream)),
        std::istreambuf_iterator<char>()
    );
    if (bytes.empty()) {
        schema_error(std::string(field) + " is empty: " + path.string());
    }
    cv::Mat image = cv::imdecode(bytes, cv::IMREAD_UNCHANGED);
    if (image.empty()) {
        schema_error(std::string(field) + " could not be read as an image: " + path.string());
    }
    if (context.reference_resize) {
        const auto& resize = *context.reference_resize;
        const auto size = roi ? OutputSize{roi->width, roi->height} : resize.output_size;
        image = FrameNormalizer{std::nullopt, size, resize.interpolation}.normalize(image);
    }
    return image;
}

DetectorPtr parse_detector(
    const YAML::Node& node,
    std::string_view field,
    const LoadContext& context
);

ConditionPtr parse_condition(
    const YAML::Node& node,
    std::string_view field,
    const LoadContext& context
);

std::vector<ConditionPtr> parse_condition_list(
    const YAML::Node& node,
    std::string_view field,
    const LoadContext& context
) {
    std::vector<ConditionPtr> result;
    for (const auto& item : as_list(node, field)) {
        result.push_back(parse_condition(item, field, context));
    }
    return result;
}

DetectorPtr parse_detector(
    const YAML::Node& node,
    std::string_view field,
    const LoadContext& context
) {
    const auto mapping = require_map(node, field);
    if (!mapping["type"]) {
        schema_error(std::string(field) + ".type is missing");
    }
    const std::string type = as_string(mapping["type"], std::string(field) + ".type");
    if (type == "template_match") {
        check_keys(mapping, {"type", "reference"}, {"roi"});
        const auto roi = parse_roi(mapping["roi"], std::string(field) + ".roi");
        return std::make_shared<TemplateMatchDetector>(
            read_reference(mapping["reference"], std::string(field) + ".reference", context, roi),
            roi
        );
    }
    if (type == "mean_absolute_similarity") {
        check_keys(mapping, {"type", "reference"}, {"roi"});
        const auto roi = parse_roi(mapping["roi"], std::string(field) + ".roi");
        return std::make_shared<MeanAbsoluteSimilarityDetector>(
            read_reference(mapping["reference"], std::string(field) + ".reference", context, roi),
            roi
        );
    }
    if (type == "root_mean_square_similarity") {
        check_keys(mapping, {"type", "reference"}, {"roi"});
        const auto roi = parse_roi(mapping["roi"], std::string(field) + ".roi");
        return std::make_shared<RootMeanSquareSimilarityDetector>(
            read_reference(mapping["reference"], std::string(field) + ".reference", context, roi),
            roi
        );
    }
    if (type == "difference_hash_similarity") {
        check_keys(mapping, {"type", "reference"}, {"hash_size", "roi"});
        const int hash_size = mapping["hash_size"]
            ? as_integer(mapping["hash_size"], std::string(field) + ".hash_size")
            : 8;
        const auto roi = parse_roi(mapping["roi"], std::string(field) + ".roi");
        return std::make_shared<DifferenceHashSimilarityDetector>(
            read_reference(mapping["reference"], std::string(field) + ".reference", context, roi),
            hash_size,
            roi
        );
    }
    if (type == "phase_correlation") {
        check_keys(mapping, {"type", "reference"}, {"roi"});
        const auto roi = parse_roi(mapping["roi"], std::string(field) + ".roi");
        return std::make_shared<PhaseCorrelationDetector>(
            read_reference(mapping["reference"], std::string(field) + ".reference", context, roi),
            roi
        );
    }
    if (type == "mean_brightness") {
        check_keys(mapping, {"type"}, {"roi"});
        return std::make_shared<MeanBrightnessDetector>(
            parse_roi(mapping["roi"], std::string(field) + ".roi")
        );
    }
    if (type == "color_range") {
        check_keys(mapping, {"type", "lower", "upper"}, {"roi"});
        const auto parse_bounds = [&](const YAML::Node& value, std::string_view bound_field) {
            std::vector<double> result;
            for (const auto& item : as_list(value, bound_field)) {
                result.push_back(as_number(item, bound_field));
            }
            return result;
        };
        return std::make_shared<ColorRangeDetector>(
            parse_bounds(mapping["lower"], std::string(field) + ".lower"),
            parse_bounds(mapping["upper"], std::string(field) + ".upper"),
            parse_roi(mapping["roi"], std::string(field) + ".roi")
        );
    }
    schema_error("unsupported detector type: " + type);
}

ConditionPtr parse_condition(
    const YAML::Node& node,
    std::string_view field,
    const LoadContext& context
) {
    const auto mapping = require_map(node, field);
    if (!mapping["type"]) {
        schema_error(std::string(field) + ".type is missing");
    }
    const std::string type = as_string(mapping["type"], std::string(field) + ".type");
    if (type == "detected") {
        check_keys(mapping, {"type", "minimum_score", "detector"});
        return std::make_shared<DetectedCondition>(
            parse_detector(mapping["detector"], std::string(field) + ".detector", context),
            as_number(mapping["minimum_score"], std::string(field) + ".minimum_score")
        );
    }
    if (type == "all") {
        check_keys(mapping, {"type", "conditions"});
        return std::make_shared<AllCondition>(
            parse_condition_list(
                mapping["conditions"],
                std::string(field) + ".conditions",
                context
            )
        );
    }
    if (type == "any") {
        check_keys(mapping, {"type", "conditions"});
        return std::make_shared<AnyCondition>(
            parse_condition_list(
                mapping["conditions"],
                std::string(field) + ".conditions",
                context
            )
        );
    }
    if (type == "not") {
        check_keys(mapping, {"type", "condition"});
        return std::make_shared<NotCondition>(
            parse_condition(mapping["condition"], std::string(field) + ".condition", context)
        );
    }
    if (type == "rising_edge") {
        check_keys(mapping, {"type", "condition"});
        return std::make_shared<RisingEdgeCondition>(
            parse_condition(mapping["condition"], std::string(field) + ".condition", context)
        );
    }
    if (type == "falling_edge") {
        check_keys(mapping, {"type", "condition"});
        return std::make_shared<FallingEdgeCondition>(
            parse_condition(mapping["condition"], std::string(field) + ".condition", context)
        );
    }
    if (type == "once") {
        check_keys(mapping, {"type", "condition"});
        return std::make_shared<OnceCondition>(
            parse_condition(mapping["condition"], std::string(field) + ".condition", context)
        );
    }
    if (type == "elapsed") {
        check_keys(mapping, {"type", "duration"});
        return std::make_shared<ElapsedCondition>(
            parse_duration(mapping["duration"], std::string(field) + ".duration")
        );
    }
    if (type == "hold") {
        check_keys(mapping, {"type", "duration", "condition"});
        return std::make_shared<HoldCondition>(
            parse_condition(mapping["condition"], std::string(field) + ".condition", context),
            parse_duration(mapping["duration"], std::string(field) + ".duration")
        );
    }
    if (type == "nth") {
        check_keys(mapping, {"type", "count", "condition"});
        return std::make_shared<NthCondition>(
            parse_condition(mapping["condition"], std::string(field) + ".condition", context),
            as_integer(mapping["count"], std::string(field) + ".count")
        );
    }
    if (type == "reset_when") {
        check_keys(mapping, {"type", "condition", "reset_condition"});
        return std::make_shared<ResetWhenCondition>(
            parse_condition(mapping["condition"], std::string(field) + ".condition", context),
            parse_condition(
                mapping["reset_condition"],
                std::string(field) + ".reset_condition",
                context
            )
        );
    }
    if (type == "then") {
        check_keys(mapping, {"type", "conditions"}, {"within"});
        std::optional<std::chrono::nanoseconds> within;
        if (mapping["within"]) {
            within = parse_duration(mapping["within"], std::string(field) + ".within");
        }
        return std::make_shared<ThenCondition>(
            parse_condition_list(
                mapping["conditions"],
                std::string(field) + ".conditions",
                context
            ),
            within
        );
    }
    schema_error("unsupported condition type: " + type);
}

std::shared_ptr<Rule> parse_rule(
    const YAML::Node& node,
    std::string_view field,
    const LoadContext& context
) {
    const auto mapping = require_map(node, field);
    check_keys(mapping, {"condition", "action"});
    const auto action_name = as_string(mapping["action"], std::string(field) + ".action");
    const auto action = parse_action(action_name);
    if (!action.has_value()) {
        schema_error("unsupported action operation: " + action_name);
    }
    return std::make_shared<Rule>(
        parse_condition(mapping["condition"], std::string(field) + ".condition", context),
        Action{*action}
    );
}

ScenarioRulePtr parse_scenario_rule(
    const YAML::Node& node,
    std::string_view field,
    const LoadContext& context
) {
    const auto mapping = require_map(node, field);
    if (mapping["sequence"]) {
        check_keys(mapping, {"sequence"});
        const auto items = as_list(mapping["sequence"], std::string(field) + ".sequence");
        if (items.empty()) {
            schema_error("rule.sequence must not be empty");
        }
        std::vector<std::shared_ptr<Rule>> rules;
        for (const auto& item : items) {
            rules.push_back(parse_rule(item, std::string(field) + ".sequence", context));
        }
        return std::make_shared<RuleSequence>(std::move(rules));
    }
    return parse_rule(node, field, context);
}

std::vector<std::optional<std::vector<ScenarioRulePtr>>> parse_splits(
    const YAML::Node& node,
    const LoadContext& context
) {
    std::vector<std::optional<std::vector<ScenarioRulePtr>>> splits;
    for (const auto& item : as_list(node, "splits")) {
        if (!item || item.IsNull()) {
            splits.push_back(std::nullopt);
            continue;
        }
        const auto mapping = require_map(item, "split");
        check_keys(mapping, {"rules"});
        std::vector<ScenarioRulePtr> rules;
        for (const auto& rule_node : as_list(mapping["rules"], "split.rules")) {
            rules.push_back(parse_scenario_rule(rule_node, "rule", context));
        }
        splits.push_back(std::move(rules));
    }
    return splits;
}

Scenario parse_scenario(const YAML::Node& root, const LoadContext& context) {
    const auto mapping = require_map(root, "scenario");
    check_keys(mapping, {"start_condition", "splits"}, {"reset_condition", "incomplete_condition"}, true);
    Scenario scenario;
    scenario.start_condition = parse_condition(mapping["start_condition"], "start_condition", context);
    if (mapping["reset_condition"] && !mapping["reset_condition"].IsNull()) {
        scenario.reset_condition =
            parse_condition(mapping["reset_condition"], "reset_condition", context);
    }
    if (mapping["incomplete_condition"] && !mapping["incomplete_condition"].IsNull()) {
        scenario.incomplete_condition =
            parse_condition(mapping["incomplete_condition"], "incomplete_condition", context);
    }
    scenario.splits = parse_splits(mapping["splits"], context);
    return scenario;
}

}  // namespace

LoadedScenario load_scenario(
    const std::filesystem::path& path,
    std::optional<ReferenceResizeOptions> reference_resize
) {
    const std::string extension = lower_extension(path);
    if (extension == ".py") {
        throw ScenarioLoadError(
            ScenarioErrorKind::unsupported_python,
            "Python scenario modules are no longer supported. Convert this scenario to YAML: " +
                path.string()
        );
    }
    if (extension != ".yaml" && extension != ".yml") {
        throw ScenarioLoadError(
            ScenarioErrorKind::schema,
            "scenario must be a .yaml or .yml file: " + path.string()
        );
    }

    std::ifstream stream{path, std::ios::binary};
    if (!stream) {
        throw ScenarioLoadError(
            ScenarioErrorKind::io,
            "could not open scenario file: " + path.string()
        );
    }

    YAML::Node root;
    try {
        root = YAML::Load(stream);
    } catch (const YAML::Exception& error) {
        throw ScenarioLoadError(
            ScenarioErrorKind::yaml,
            "could not parse scenario YAML: " + std::string(error.what())
        );
    }

    try {
        return LoadedScenario{parse_scenario(root, LoadContext{path.parent_path(), reference_resize}), path};
    } catch (const ScenarioLoadError&) {
        throw;
    } catch (const std::exception& error) {
        throw ScenarioLoadError(ScenarioErrorKind::schema, error.what());
    }
}

}  // namespace divergencesplitter
