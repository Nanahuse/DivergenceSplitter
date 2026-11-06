#include "divergencesplitter/scenario/scenario.hpp"

#include <opencv2/imgcodecs.hpp>

#include <ryml/ryml.hpp>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <limits>
#include <locale>
#include <map>
#include <regex>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detectors.hpp"
#include "divergencesplitter/text.hpp"

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

// Missing children are represented by an invalid reference, never a seeded node.
ryml::ConstNodeRef child(ryml::ConstNodeRef node, std::string_view key) {
    if (node.invalid() || !node.is_map()) {
        return {};
    }
    return node.find_child(ryml::csubstr{key.data(), key.size()});
}

bool is_null(ryml::ConstNodeRef node) {
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

ryml::ConstNodeRef require_map(ryml::ConstNodeRef node, std::string_view field) {
    if (node.invalid() || !node.is_map()) {
        schema_error(std::string(field) + " must be a mapping");
    }
    return node;
}

std::string copy_scalar(ryml::csubstr value) {
    return value.len ? std::string{value.str, value.len} : std::string{};
}

std::string as_string(ryml::ConstNodeRef node, std::string_view field) {
    if (node.invalid() || !node.has_val() || is_null(node)) {
        schema_error(std::string(field) + " must be a string");
    }
    return copy_scalar(node.val());
}

template <typename Number>
Number as_numeric(ryml::ConstNodeRef node, std::string_view field, const char* type) {
    if (!node.invalid() && node.has_val() && !is_null(node)) {
        // Match the previous loader's classic-locale scalar conversions,
        // including octal/hex integers, signs, and trailing whitespace.
        std::istringstream stream{copy_scalar(node.val())};
        stream.imbue(std::locale::classic());
        stream.unsetf(std::ios::dec);
        Number value{};
        if ((stream >> std::noskipws >> value) && (stream >> std::ws).eof()
            && std::isfinite(static_cast<double>(value))) {
            return value;
        }
    }
    schema_error(std::string(field) + " must be " + type);
}

double as_number(ryml::ConstNodeRef node, std::string_view field) {
    return as_numeric<double>(node, field, "a number");
}

int as_integer(ryml::ConstNodeRef node, std::string_view field) {
    return as_numeric<int>(node, field, "an integer");
}

std::vector<ryml::ConstNodeRef> as_list(ryml::ConstNodeRef node, std::string_view field) {
    if (node.invalid() || !node.is_seq()) {
        schema_error(std::string(field) + " must be a list");
    }
    std::vector<ryml::ConstNodeRef> result;
    result.reserve(node.num_children());
    for (const auto item : node.children()) {
        result.push_back(item);
    }
    return result;
}

void check_keys(
    const ryml::ConstNodeRef& node,
    const StringSet& required,
    const StringSet& optional = {},
    bool allow_unknown = false
) {
    StringSet present;
    for (const auto entry : node.children()) {
        if (!entry.has_key() || entry.key_is_null()) {
            schema_error("mapping keys must be strings");
        }
        const auto key = copy_scalar(entry.key());
        if (!present.insert(key).second) {
            schema_error("duplicate scenario field: " + key);
        }
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

[[noreturn]] void yaml_error(const std::string& message) {
    throw ScenarioLoadError(ScenarioErrorKind::yaml, "could not parse scenario YAML: " + message);
}

ryml::Callbacks yaml_callbacks() {
    ryml::Callbacks callbacks;
    callbacks.set_error_basic([](ryml::csubstr message, const ryml::ErrorDataBasic&, void*) {
        yaml_error(copy_scalar(message));
    });
    callbacks.set_error_parse([](ryml::csubstr message, const ryml::ErrorDataParse& data, void*) {
        yaml_error(copy_scalar(message) + " at line " + std::to_string(data.ymlloc.line + 1)
                   + ", column " + std::to_string(data.ymlloc.col + 1));
    });
    callbacks.set_error_visit([](ryml::csubstr message, const ryml::ErrorDataVisit&, void*) {
        yaml_error(copy_scalar(message));
    });
    return callbacks;
}

// ryml's resolver copies containers recursively and does not guard alias cycles.
// Validate references and merge operand types before calling it; expansion and
// precedence remain entirely the library's responsibility. Raw duplicates must
// also be rejected before resolution can hide them.
void validate_yaml(ryml::ConstNodeRef root) {
    std::map<std::string, ryml::ConstNodeRef> anchors;
    const auto visit = [&](auto&& self, ryml::ConstNodeRef node) -> void {
        const auto target = [&](ryml::csubstr name) {
            const auto found = anchors.find(copy_scalar(name));
            if (found == anchors.end()) {
                yaml_error("anchor not found: " + copy_scalar(name));
            }
            const auto value = found->second;
            if (!value.invalid() && (value.id() == node.id()
                || node.tree()->is_ancestor(node.id(), value.id()))) {
                yaml_error("cyclic alias: " + copy_scalar(name));
            }
            return value;
        };
        if (node.is_key_ref()) {
            const auto value = target(node.key_ref());
            if (!value.invalid() && value.is_container()) {
                schema_error("mapping keys must be strings");
            }
        }
        if (node.is_val_ref()) {
            const auto value = target(node.val_ref());
            const auto parent = node.parent();
            const bool merge = (node.has_key() && node.key() == "<<")
                || (!parent.invalid() && parent.is_seq() && parent.has_key() && parent.key() == "<<");
            if (merge && (value.invalid() || !value.is_map())) {
                yaml_error("merge aliases must refer to mappings");
            }
        }
        // A key anchor always denotes a scalar, even when its value is a map.
        if (node.has_key_anchor()) {
            anchors[copy_scalar(node.key_anchor())] = {};
        }
        if (node.has_val_anchor()) {
            anchors[copy_scalar(node.val_anchor())] = node;
        }
        if (node.has_key() && node.key() == "<<") {
            if (node.is_seq()) {
                for (const auto item : node.children()) {
                    if (!item.is_val_ref()) {
                        yaml_error("merge sequences must contain mapping aliases");
                    }
                }
            } else if (!node.is_val_ref()) {
                // A literal scalar << is left for normal schema validation.
                if (node.is_container()) {
                    yaml_error("merge values must be mapping aliases or lists of mapping aliases");
                }
            }
        }
        StringSet keys;
        for (const auto item : node.children()) {
            if (node.is_map() && !item.is_key_ref()) {
                if (item.key_is_null()) {
                    schema_error("mapping keys must be strings");
                }
                const auto key = copy_scalar(item.key());
                if (!keys.insert(key).second) {
                    schema_error("duplicate scenario field: " + key);
                }
            }
            self(self, item);
        }
    };
    visit(visit, root);
}

std::chrono::nanoseconds parse_duration(const ryml::ConstNodeRef& node, std::string_view field) {
    static const std::regex pattern{R"(^(\d+(?:\.\d+)?)(ms|s)$)"};
    const std::string text = as_string(node, field);
    std::smatch match;
    if (!std::regex_match(text, match, pattern)) {
        schema_error(std::string(field) + " must be a duration like '500ms' or '3s'");
    }
    const double amount = std::stod(match[1].str());
    const std::string unit = match[2].str();
    const double nanoseconds = amount * (unit == "s" ? 1'000'000'000.0 : 1'000'000.0);
    if (!std::isfinite(nanoseconds) || nanoseconds < 0.0
        || nanoseconds >= static_cast<double>((std::numeric_limits<std::int64_t>::max)())) {
        schema_error(std::string(field) + " duration is invalid");
    }
    return std::chrono::nanoseconds{static_cast<std::int64_t>(nanoseconds)};
}

std::optional<Region> parse_roi(const ryml::ConstNodeRef& node, std::string_view field) {
    if (node.invalid() || is_null(node)) {
        return std::nullopt;
    }
    const auto mapping = require_map(node, field);
    check_keys(mapping, {"x", "y", "width", "height"});
    Region region{
        as_integer(child(mapping, "x"), std::string(field) + ".x"),
        as_integer(child(mapping, "y"), std::string(field) + ".y"),
        as_integer(child(mapping, "width"), std::string(field) + ".width"),
        as_integer(child(mapping, "height"), std::string(field) + ".height"),
    };
    if (!region.valid()) {
        schema_error(std::string(field) + " must be non-negative with positive dimensions");
    }
    return region;
}

cv::Mat read_reference(
    const ryml::ConstNodeRef& node,
    std::string_view field,
    const LoadContext& context,
    const std::optional<Region>& roi
) {
    std::filesystem::path path = path_from_utf8(as_string(node, field));
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
    const ryml::ConstNodeRef& node,
    std::string_view field,
    const LoadContext& context
);

ConditionPtr parse_condition(
    const ryml::ConstNodeRef& node,
    std::string_view field,
    const LoadContext& context
);

std::vector<ConditionPtr> parse_condition_list(
    const ryml::ConstNodeRef& node,
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
    const ryml::ConstNodeRef& node,
    std::string_view field,
    const LoadContext& context
) {
    const auto mapping = require_map(node, field);
    if (child(mapping, "type").invalid()) {
        schema_error(std::string(field) + ".type is missing");
    }
    const std::string type = as_string(child(mapping, "type"), std::string(field) + ".type");
    if (type == "template_match") {
        check_keys(mapping, {"type", "reference"}, {"roi"});
        const auto roi = parse_roi(child(mapping, "roi"), std::string(field) + ".roi");
        return std::make_shared<TemplateMatchDetector>(
            read_reference(child(mapping, "reference"), std::string(field) + ".reference", context, roi),
            roi
        );
    }
    if (type == "mean_absolute_similarity") {
        check_keys(mapping, {"type", "reference"}, {"roi"});
        const auto roi = parse_roi(child(mapping, "roi"), std::string(field) + ".roi");
        return std::make_shared<MeanAbsoluteSimilarityDetector>(
            read_reference(child(mapping, "reference"), std::string(field) + ".reference", context, roi),
            roi
        );
    }
    if (type == "root_mean_square_similarity") {
        check_keys(mapping, {"type", "reference"}, {"roi"});
        const auto roi = parse_roi(child(mapping, "roi"), std::string(field) + ".roi");
        return std::make_shared<RootMeanSquareSimilarityDetector>(
            read_reference(child(mapping, "reference"), std::string(field) + ".reference", context, roi),
            roi
        );
    }
    if (type == "histogram_similarity") {
        check_keys(mapping, {"type", "reference"}, {"roi"});
        const auto roi = parse_roi(child(mapping, "roi"), std::string(field) + ".roi");
        return std::make_shared<HistogramSimilarityDetector>(
            read_reference(child(mapping, "reference"), std::string(field) + ".reference", context, roi),
            roi
        );
    }
    if (type == "perceptual_hash_similarity") {
        check_keys(mapping, {"type", "reference"}, {"roi"});
        const auto roi = parse_roi(child(mapping, "roi"), std::string(field) + ".roi");
        return std::make_shared<PerceptualHashSimilarityDetector>(
            read_reference(child(mapping, "reference"), std::string(field) + ".reference", context, roi),
            roi
        );
    }
    if (type == "difference_hash_similarity") {
        check_keys(mapping, {"type", "reference"}, {"hash_size", "roi"});
        const int hash_size = !child(mapping, "hash_size").invalid()
            ? as_integer(child(mapping, "hash_size"), std::string(field) + ".hash_size")
            : 8;
        const auto roi = parse_roi(child(mapping, "roi"), std::string(field) + ".roi");
        return std::make_shared<DifferenceHashSimilarityDetector>(
            read_reference(child(mapping, "reference"), std::string(field) + ".reference", context, roi),
            hash_size,
            roi
        );
    }
    if (type == "phase_correlation") {
        check_keys(mapping, {"type", "reference"}, {"roi"});
        const auto roi = parse_roi(child(mapping, "roi"), std::string(field) + ".roi");
        return std::make_shared<PhaseCorrelationDetector>(
            read_reference(child(mapping, "reference"), std::string(field) + ".reference", context, roi),
            roi
        );
    }
    if (type == "mean_brightness") {
        check_keys(mapping, {"type"}, {"roi"});
        return std::make_shared<MeanBrightnessDetector>(
            parse_roi(child(mapping, "roi"), std::string(field) + ".roi")
        );
    }
    if (type == "color_range") {
        check_keys(mapping, {"type", "lower", "upper"}, {"roi"});
        const auto parse_bounds = [&](const ryml::ConstNodeRef& value, std::string_view bound_field) {
            std::vector<double> result;
            for (const auto& item : as_list(value, bound_field)) {
                result.push_back(as_number(item, bound_field));
            }
            return result;
        };
        return std::make_shared<ColorRangeDetector>(
            parse_bounds(child(mapping, "lower"), std::string(field) + ".lower"),
            parse_bounds(child(mapping, "upper"), std::string(field) + ".upper"),
            parse_roi(child(mapping, "roi"), std::string(field) + ".roi")
        );
    }
    schema_error("unsupported detector type: " + type);
}

ConditionPtr parse_condition(
    const ryml::ConstNodeRef& node,
    std::string_view field,
    const LoadContext& context
) {
    const auto mapping = require_map(node, field);
    if (child(mapping, "type").invalid()) {
        schema_error(std::string(field) + ".type is missing");
    }
    const std::string type = as_string(child(mapping, "type"), std::string(field) + ".type");
    if (type == "detected") {
        check_keys(mapping, {"type", "minimum_score", "detector"});
        return std::make_shared<DetectedCondition>(
            parse_detector(child(mapping, "detector"), std::string(field) + ".detector", context),
            as_number(child(mapping, "minimum_score"), std::string(field) + ".minimum_score")
        );
    }
    if (type == "all") {
        check_keys(mapping, {"type", "conditions"});
        return std::make_shared<AllCondition>(
            parse_condition_list(
                child(mapping, "conditions"),
                std::string(field) + ".conditions",
                context
            )
        );
    }
    if (type == "any") {
        check_keys(mapping, {"type", "conditions"});
        return std::make_shared<AnyCondition>(
            parse_condition_list(
                child(mapping, "conditions"),
                std::string(field) + ".conditions",
                context
            )
        );
    }
    if (type == "not") {
        check_keys(mapping, {"type", "condition"});
        return std::make_shared<NotCondition>(
            parse_condition(child(mapping, "condition"), std::string(field) + ".condition", context)
        );
    }
    if (type == "rising_edge") {
        check_keys(mapping, {"type", "condition"});
        return std::make_shared<RisingEdgeCondition>(
            parse_condition(child(mapping, "condition"), std::string(field) + ".condition", context)
        );
    }
    if (type == "falling_edge") {
        check_keys(mapping, {"type", "condition"});
        return std::make_shared<FallingEdgeCondition>(
            parse_condition(child(mapping, "condition"), std::string(field) + ".condition", context)
        );
    }
    if (type == "once") {
        check_keys(mapping, {"type", "condition"});
        return std::make_shared<OnceCondition>(
            parse_condition(child(mapping, "condition"), std::string(field) + ".condition", context)
        );
    }
    if (type == "elapsed") {
        check_keys(mapping, {"type", "duration"});
        return std::make_shared<ElapsedCondition>(
            parse_duration(child(mapping, "duration"), std::string(field) + ".duration")
        );
    }
    if (type == "hold") {
        check_keys(mapping, {"type", "duration", "condition"});
        return std::make_shared<HoldCondition>(
            parse_condition(child(mapping, "condition"), std::string(field) + ".condition", context),
            parse_duration(child(mapping, "duration"), std::string(field) + ".duration")
        );
    }
    if (type == "nth") {
        check_keys(mapping, {"type", "count", "condition"});
        return std::make_shared<NthCondition>(
            parse_condition(child(mapping, "condition"), std::string(field) + ".condition", context),
            as_integer(child(mapping, "count"), std::string(field) + ".count")
        );
    }
    if (type == "reset_when") {
        check_keys(mapping, {"type", "condition", "reset_condition"});
        return std::make_shared<ResetWhenCondition>(
            parse_condition(child(mapping, "condition"), std::string(field) + ".condition", context),
            parse_condition(
                child(mapping, "reset_condition"),
                std::string(field) + ".reset_condition",
                context
            )
        );
    }
    if (type == "then") {
        check_keys(mapping, {"type", "conditions"}, {"within"});
        std::optional<std::chrono::nanoseconds> within;
        if (!child(mapping, "within").invalid()) {
            within = parse_duration(child(mapping, "within"), std::string(field) + ".within");
        }
        return std::make_shared<ThenCondition>(
            parse_condition_list(
                child(mapping, "conditions"),
                std::string(field) + ".conditions",
                context
            ),
            within
        );
    }
    schema_error("unsupported condition type: " + type);
}

std::shared_ptr<Rule> parse_rule(
    const ryml::ConstNodeRef& node,
    std::string_view field,
    const LoadContext& context
) {
    const auto mapping = require_map(node, field);
    check_keys(mapping, {"condition", "action"});
    const auto action_name = as_string(child(mapping, "action"), std::string(field) + ".action");
    const auto action = parse_action(action_name);
    if (!action.has_value()) {
        schema_error("unsupported action operation: " + action_name);
    }
    return std::make_shared<Rule>(
        parse_condition(child(mapping, "condition"), std::string(field) + ".condition", context),
        Action{*action}
    );
}

ScenarioRulePtr parse_scenario_rule(
    const ryml::ConstNodeRef& node,
    std::string_view field,
    const LoadContext& context
) {
    const auto mapping = require_map(node, field);
    if (!child(mapping, "sequence").invalid()) {
        check_keys(mapping, {"sequence"});
        const auto items = as_list(child(mapping, "sequence"), std::string(field) + ".sequence");
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
    const ryml::ConstNodeRef& node,
    const LoadContext& context
) {
    std::vector<std::optional<std::vector<ScenarioRulePtr>>> splits;
    for (const auto& item : as_list(node, "splits")) {
        if (is_null(item)) {
            splits.push_back(std::nullopt);
            continue;
        }
        const auto mapping = require_map(item, "split");
        check_keys(mapping, {"rules"});
        std::vector<ScenarioRulePtr> rules;
        for (const auto& rule_node : as_list(child(mapping, "rules"), "split.rules")) {
            rules.push_back(parse_scenario_rule(rule_node, "rule", context));
        }
        splits.push_back(std::move(rules));
    }
    return splits;
}

Scenario parse_scenario(const ryml::ConstNodeRef& root, const LoadContext& context) {
    const auto mapping = require_map(root, "scenario");
    check_keys(mapping, {"start_condition", "splits"}, {"reset_condition", "incomplete_condition"}, true);
    Scenario scenario;
    scenario.start_condition = parse_condition(child(mapping, "start_condition"), "start_condition", context);
    if (!child(mapping, "reset_condition").invalid() && !is_null(child(mapping, "reset_condition"))) {
        scenario.reset_condition =
            parse_condition(child(mapping, "reset_condition"), "reset_condition", context);
    }
    if (!child(mapping, "incomplete_condition").invalid() && !is_null(child(mapping, "incomplete_condition"))) {
        scenario.incomplete_condition =
            parse_condition(child(mapping, "incomplete_condition"), "incomplete_condition", context);
    }
    scenario.splits = parse_splits(child(mapping, "splits"), context);
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

    const std::string source{std::istreambuf_iterator<char>{stream}, std::istreambuf_iterator<char>{}};
    if (stream.bad()) {
        throw ScenarioLoadError(ScenarioErrorKind::io, "could not read scenario file: " + path.string());
    }
    // Parser and Tree own their callbacks. Never change ryml's global handlers.
    const auto callbacks = yaml_callbacks();
    ryml::Tree tree{callbacks};
    ryml::EventHandlerTree handler{callbacks};
    ryml::Parser parser{&handler};
    const auto filename = path.string();
    ryml::parse_in_arena(&parser, ryml::csubstr{filename.data(), filename.size()},
                        ryml::csubstr{source.data(), source.size()}, &tree);
    ryml::ConstNodeRef root = tree.crootref();
    if (root.is_stream()) {
        // yaml-cpp loaded the first document only. Keep that behavior, and do
        // not allow anchors from subsequent documents to affect this one.
        if (root.num_children() == 0) {
            schema_error("scenario must be a mapping");
        }
        root = root.first_child();
        while (!root.next_sibling().invalid()) {
            tree.remove(root.next_sibling().id());
        }
    }
    validate_yaml(root);
    tree.resolve();

    try {
        return LoadedScenario{parse_scenario(root, LoadContext{path.parent_path(), reference_resize}), path};
    } catch (const ScenarioLoadError&) {
        throw;
    } catch (const std::exception& error) {
        throw ScenarioLoadError(ScenarioErrorKind::schema, error.what());
    }
}

}  // namespace divergencesplitter
