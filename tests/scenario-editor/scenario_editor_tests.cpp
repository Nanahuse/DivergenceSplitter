#include <gtest/gtest.h>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <string>
#include <string_view>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/scenario/editor/document.hpp"
#include "divergencesplitter/scenario/editor/model.hpp"
#include "divergencesplitter/scenario/scenario.hpp"

using namespace divergencesplitter;
using namespace divergencesplitter::scenario_editor;

namespace {

class TemporaryDirectory {
public:
    TemporaryDirectory() {
        static int counter = 0;
        path_ = std::filesystem::temp_directory_path()
            / ("divergencesplitter-editor-v2-" + std::to_string(++counter) + "-"
               + std::to_string(std::chrono::steady_clock::now().time_since_epoch().count()));
        std::filesystem::create_directories(path_);
    }
    ~TemporaryDirectory() {
        std::error_code error;
        std::filesystem::remove_all(path_, error);
    }
    [[nodiscard]] const std::filesystem::path& path() const { return path_; }

private:
    std::filesystem::path path_;
};

void write_text(const std::filesystem::path& path, std::string_view text) {
    std::ofstream stream{path, std::ios::binary};
    stream << text;
}

std::string read_text(const std::filesystem::path& path) {
    std::ifstream stream{path, std::ios::binary};
    return {std::istreambuf_iterator<char>{stream}, std::istreambuf_iterator<char>{}};
}

const Value& require_setting(const Value& value, std::string_view key) {
    const auto* setting = value.find(key);
    EXPECT_NE(setting, nullptr) << key;
    static const Value missing = Value::make_null();
    return setting == nullptr ? missing : *setting;
}

std::string scalar_setting(const Value& value, std::string_view key) {
    const auto& setting = require_setting(value, key);
    EXPECT_TRUE(setting.is_scalar()) << key;
    return setting.scalar;
}

const Value& require_condition(const Value& conditions_parent, std::size_t index) {
    const auto* conditions = conditions_parent.find("conditions");
    EXPECT_NE(conditions, nullptr);
    static const Value missing = Value::make_null();
    if (conditions == nullptr) {
        return missing;
    }
    const auto* item = conditions->find_index(index);
    EXPECT_NE(item, nullptr) << index;
    return item == nullptr ? missing : *item;
}

nlohmann::json path(std::initializer_list<nlohmann::json> parts) {
    nlohmann::json result = nlohmann::json::array();
    for (const auto& part : parts) {
        result.push_back(part);
    }
    return result;
}

}  // namespace

TEST(ScenarioEditorV2, ImportsDefinitionsParametersAndUses) {
    auto document = import_scenario_yaml(R"(
schema_version: 2
definitions:
  conditions:
    wait:
      parameters:
        wait_duration: 1s
      condition:
        type: elapsed
        duration: {param: wait_duration}
start_condition:
  use: wait
  with:
    wait_duration: 2s
splits: []
)");
    ASSERT_EQ(document.definitions.conditions.size(), 1U);
    EXPECT_EQ(document.definitions.conditions[0].name, "wait");
    ASSERT_EQ(document.definitions.conditions[0].parameters.size(), 1U);
    EXPECT_EQ(document.definitions.conditions[0].parameters[0].name, "wait_duration");
    ASSERT_TRUE(document.start_condition.has_value());
    EXPECT_TRUE(document.start_condition->is_shared_use());
    EXPECT_EQ(document.start_condition->use_name(), "wait");
    const auto resolved = resolved_condition(document, document.start_condition->value);
    EXPECT_EQ(scalar_setting(resolved, "duration"), "2s");
}

TEST(ScenarioEditorV2, ExportPreservesSharedUsageAndRunsWithTheOverriddenDuration) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, R"(
schema_version: 2
definitions:
  conditions:
    wait:
      parameters:
        duration: 1s
      condition:
        type: elapsed
        duration: {param: duration}
start_condition:
  use: wait
  with:
    duration: 3s
splits: []
)");
    const auto document = load_scenario_document(path);
    const auto exported = export_scenario_yaml(document);
    const auto exported_path = directory.path() / "exported.yaml";
    write_text(exported_path, exported);

    const auto reloaded = load_scenario_document(exported_path);
    const auto* definition = find_condition_definition(reloaded, "wait");
    ASSERT_NE(definition, nullptr);
    ASSERT_TRUE(reloaded.start_condition);
    EXPECT_EQ(reloaded.start_condition->use_name(), "wait");
    const auto& parameter = require_setting(definition->condition, "duration");
    ASSERT_TRUE(parameter.is_parameter_reference());
    EXPECT_EQ(parameter.scalar, "duration");

    const auto loaded = load_scenario(exported_path);
    ASSERT_TRUE(loaded.scenario.start_condition);
    using namespace std::chrono_literals;
    const cv::Mat image(1, 1, CV_8UC3, cv::Scalar::all(0));
    const auto evaluate_at = [&](std::chrono::nanoseconds time) {
        const MonotonicTime timestamp{time.count()};
        FrameContext context{Frame{image, timestamp}, timestamp};
        return loaded.scenario.start_condition->evaluate(context);
    };
    EXPECT_EQ(evaluate_at(0s), false);
    EXPECT_EQ(evaluate_at(2999ms), false);
    EXPECT_EQ(evaluate_at(3s), true);
}

TEST(ScenarioEditorV2, ExplicitExposureAllowsPerUsageOverrideAndReset) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "wait"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "wait"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "wait"},
        {"setting_path", path({"duration"})},
    });

    auto* definition = find_condition_definition(session.document, "wait");
    ASSERT_NE(definition, nullptr);
    ASSERT_EQ(definition->parameters.size(), 1U);
    const auto parameter = definition->parameters[0].name;
    EXPECT_EQ(definition->parameters[0].default_value.scalar, "1s");
    const auto* raw_duration = definition->condition.find("duration");
    ASSERT_NE(raw_duration, nullptr);
    EXPECT_TRUE(raw_duration->is_parameter_reference());
    EXPECT_EQ(raw_duration->scalar, parameter);

    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "wait"},
        {"setting_path", path({"duration"})},
    });
    EXPECT_EQ(definition->parameters.size(), 1U);

    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage_setting"},
        {"path", path({"start_condition"})},
        {"setting_path", path({"duration"})},
        {"value", "2s"},
    });
    ASSERT_TRUE(session.document.start_condition.has_value());
    const auto* with = session.document.start_condition->with();
    ASSERT_NE(with, nullptr);
    ASSERT_NE(with->find(parameter), nullptr);
    EXPECT_EQ(with->find(parameter)->scalar, "2s");
    EXPECT_EQ(
        scalar_setting(resolved_condition(session.document, session.document.start_condition->value),
                       "duration"),
        "2s"
    );

    apply_editor_command(session, nlohmann::json{
        {"type", "reset_usage_setting"},
        {"path", path({"start_condition"})},
        {"setting_path", path({"duration"})},
    });
    EXPECT_EQ(session.document.start_condition->with(), nullptr);
    EXPECT_EQ(
        scalar_setting(resolved_condition(session.document, session.document.start_condition->value),
                       "duration"),
        "1s"
    );

    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_NE(session.document.start_condition->with(), nullptr);
    apply_editor_command(session, nlohmann::json{{"type", "redo"}});
    EXPECT_EQ(session.document.start_condition->with(), nullptr);
}

TEST(ScenarioEditorV2, DefinitionDefaultChangeAppliesOnlyToUnboundUsages) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "wait"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "wait"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "wait"},
        {"setting_path", path({"duration"})},
    });
    apply_editor_command(session, nlohmann::json{{"type", "add_split"}, {"index", 0}});
    apply_editor_command(session, nlohmann::json{{"type", "add_rule"}, {"split", 0}});
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"splits", 0, "rules", 0, "condition"})},
        {"name", "wait"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage_setting"},
        {"path", path({"splits", 0, "rules", 0, "condition"})},
        {"setting_path", path({"duration"})},
        {"value", "2s"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_definition_setting"},
        {"kind", "condition"},
        {"name", "wait"},
        {"setting_path", path({"duration"})},
        {"value", "3s"},
    });

    const auto start = resolved_condition(session.document, session.document.start_condition->value);
    const auto rule = resolved_condition(
        session.document,
        session.document.splits[0]->rules[0].rule.condition.value
    );
    EXPECT_EQ(scalar_setting(start, "duration"), "3s");
    EXPECT_EQ(scalar_setting(rule, "duration"), "2s");
}
TEST(ScenarioEditorV2, DefinitionStructureChangesPropagateToUsages) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "both"},
        {"value", {
            {"type", "all"},
            {"conditions", nlohmann::json::array({
                {{"type", "elapsed"}, {"duration", "1s"}},
                {{"type", "elapsed"}, {"duration", "2s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "both"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "add_condition"},
        {"path", path({"definitions", "conditions", "both"})},
        {"index", 2},
        {"value", {{"type", "elapsed"}, {"duration", "3s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "move_condition"},
        {"path", path({"definitions", "conditions", "both"})},
        {"from", 2},
        {"to", 0},
    });
    auto resolved = resolved_condition(session.document, session.document.start_condition->value);
    ASSERT_EQ(resolved.find("conditions")->sequence.size(), 3U);
    EXPECT_EQ(scalar_setting(require_condition(resolved, 0), "duration"), "3s");

    apply_editor_command(session, nlohmann::json{
        {"type", "remove_condition"},
        {"path", path({"definitions", "conditions", "both"})},
        {"index", 0},
    });
    resolved = resolved_condition(session.document, session.document.start_condition->value);
    ASSERT_EQ(resolved.find("conditions")->sequence.size(), 2U);
    EXPECT_EQ(scalar_setting(require_condition(resolved, 0), "duration"), "1s");
}

TEST(ScenarioEditorV2, ExposesNestedDetectorParameterThroughCondition) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_detector_definition"},
        {"name", "bright"},
        {"value", {
            {"type", "mean_brightness"},
            {"roi", {{"x", "0"}, {"y", "0"}, {"width", "8"}, {"height", "8"}}},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "detector"},
        {"name", "bright"},
        {"setting_path", path({"roi", "x"})},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "detect"},
        {"value", {
            {"type", "detected"},
            {"minimum_score", "0.5"},
            {"detector", {{"type", "mean_brightness"}}},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_detector"},
        {"path", path({"definitions", "conditions", "detect", "detector"})},
        {"name", "bright"},
    });
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "expose_parameter"},
            {"kind", "condition"},
            {"name", "detect"},
            {"setting_path", path({"detector", "roi", "y"})},
        }),
        ScenarioEditorError
    );
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "detect"},
        {"setting_path", path({"detector", "roi", "x"})},
    });

    auto* detector = find_detector_definition(session.document, "bright");
    ASSERT_NE(detector, nullptr);
    ASSERT_EQ(detector->parameters.size(), 1U);
    const auto detector_parameter = detector->parameters[0].name;
    EXPECT_EQ(detector->parameters[0].default_value.scalar, "0");
    ASSERT_TRUE(detector->detector.find("roi")->find("x")->is_parameter_reference());
    EXPECT_EQ(
        detector->detector.find("roi")->find("x")->scalar,
        detector_parameter
    );

    auto* condition = find_condition_definition(session.document, "detect");
    ASSERT_NE(condition, nullptr);
    ASSERT_EQ(condition->parameters.size(), 1U);
    const auto condition_parameter = condition->parameters[0].name;
    const auto* detector_use = condition->condition.find("detector");
    ASSERT_NE(detector_use, nullptr);
    const auto* with = detector_use->find("with");
    ASSERT_NE(with, nullptr);
    ASSERT_NE(with->find(detector_parameter), nullptr);
    EXPECT_TRUE(with->find(detector_parameter)->is_parameter_reference());
    EXPECT_EQ(with->find(detector_parameter)->scalar, condition_parameter);

    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "detect"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage_setting"},
        {"path", path({"start_condition"})},
        {"setting_path", path({"detector", "roi", "x"})},
        {"value", "2"},
    });
    apply_editor_command(session, nlohmann::json{{"type", "add_split"}, {"index", 0}});
    apply_editor_command(session, nlohmann::json{{"type", "add_rule"}, {"split", 0}});
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"splits", 0, "rules", 0, "condition"})},
        {"name", "detect"},
    });

    const auto start = resolved_condition(session.document, session.document.start_condition->value);
    const auto unbound = resolved_condition(
        session.document,
        session.document.splits[0]->rules[0].rule.condition.value
    );
    EXPECT_EQ(scalar_setting(*start.find("detector")->find("roi"), "x"), "2");
    EXPECT_EQ(scalar_setting(*unbound.find("detector")->find("roi"), "x"), "0");
    const auto state = editor_state_json(session);
    const auto usages = state["document"]["condition_usages"];
    const auto start_usage = std::find_if(
        usages.begin(),
        usages.end(),
        [&](const auto& item) {
            return item["path"] == path({"start_condition"});
        }
    );
    ASSERT_NE(start_usage, usages.end());
    const auto start_overrides = (*start_usage)["overrides"];
    ASSERT_EQ(start_overrides.size(), 1U);
    EXPECT_EQ(start_overrides[0]["path"], path({"detector", "roi", "x"}));
    EXPECT_EQ(start_overrides[0]["default"], "0");
    EXPECT_EQ(start_overrides[0]["value"], "2");

    apply_editor_command(session, nlohmann::json{
        {"type", "set_definition_setting"},
        {"kind", "condition"},
        {"name", "detect"},
        {"setting_path", path({"detector", "roi", "x"})},
        {"value", "3"},
    });
    const auto updated_start = resolved_condition(
        session.document, session.document.start_condition->value
    );
    const auto updated_unbound = resolved_condition(
        session.document,
        session.document.splits[0]->rules[0].rule.condition.value
    );
    EXPECT_EQ(scalar_setting(*updated_start.find("detector")->find("roi"), "x"), "2");
    EXPECT_EQ(scalar_setting(*updated_unbound.find("detector")->find("roi"), "x"), "3");

    apply_editor_command(session, nlohmann::json{
        {"type", "unexpose_parameter"},
        {"kind", "condition"},
        {"name", "detect"},
        {"setting_path", path({"detector", "roi", "x"})},
    });
    auto* unexposed = find_condition_definition(session.document, "detect");
    ASSERT_NE(unexposed, nullptr);
    EXPECT_TRUE(unexposed->parameters.empty());
    const auto* fixed_use = unexposed->condition.find("detector");
    ASSERT_NE(fixed_use, nullptr);
    const auto* fixed_with = fixed_use->find("with");
    ASSERT_NE(fixed_with, nullptr);
    EXPECT_EQ(fixed_with->find(detector_parameter)->scalar, "3");
    EXPECT_EQ(session.document.start_condition->with(), nullptr);
    EXPECT_EQ(
        scalar_setting(
            *resolved_condition(session.document, session.document.start_condition->value)
                 .find("detector")->find("roi"),
            "x"
        ),
        "3"
    );
}

TEST(ScenarioEditorV2, UnexposeRestoresDefaultAndClearsUsageOverrides) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "wait"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "wait"},
        {"setting_path", path({"duration"})},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "wait"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage_setting"},
        {"path", path({"start_condition"})},
        {"setting_path", path({"duration"})},
        {"value", "2s"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "unexpose_parameter"},
        {"kind", "condition"},
        {"name", "wait"},
        {"setting_path", path({"duration"})},
    });

    auto* definition = find_condition_definition(session.document, "wait");
    ASSERT_NE(definition, nullptr);
    EXPECT_TRUE(definition->parameters.empty());
    EXPECT_EQ(scalar_setting(definition->condition, "duration"), "1s");
    EXPECT_EQ(session.document.start_condition->with(), nullptr);
    EXPECT_EQ(
        scalar_setting(
            resolved_condition(session.document, session.document.start_condition->value),
            "duration"
        ),
        "1s"
    );

    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    definition = find_condition_definition(session.document, "wait");
    ASSERT_NE(definition, nullptr);
    ASSERT_EQ(definition->parameters.size(), 1U);
    EXPECT_TRUE(definition->condition.find("duration")->is_parameter_reference());
    EXPECT_NE(session.document.start_condition->with(), nullptr);
}
TEST(ScenarioEditorV2, UnexposeReplacesEveryReferenceToTheParameter) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_detector_definition"},
        {"name", "bright"},
        {"value", {
            {"type", "mean_brightness"},
            {"roi", {{"x", "0"}, {"y", "0"}, {"width", "8"}, {"height", "8"}}},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "detector"},
        {"name", "bright"},
        {"setting_path", path({"roi", "x"})},
    });
    auto* definition = find_detector_definition(session.document, "bright");
    ASSERT_NE(definition, nullptr);
    ASSERT_EQ(definition->parameters.size(), 1U);
    const auto parameter = definition->parameters[0].name;
    apply_editor_command(session, nlohmann::json{
        {"type", "set_value"},
        {"path", path({"definitions", "detectors", "bright", "roi", "y"})},
        {"value", {{"$param", parameter}}},
    });
    definition = find_detector_definition(session.document, "bright");
    ASSERT_NE(definition, nullptr);
    EXPECT_TRUE(
        definition->detector.find("roi")->find("y")->is_parameter_reference()
    );

    apply_editor_command(session, nlohmann::json{
        {"type", "unexpose_parameter"},
        {"kind", "detector"},
        {"name", "bright"},
        {"setting_path", path({"roi", "x"})},
    });
    definition = find_detector_definition(session.document, "bright");
    ASSERT_NE(definition, nullptr);
    EXPECT_TRUE(definition->parameters.empty());
    const auto* roi = definition->detector.find("roi");
    ASSERT_NE(roi, nullptr);
    EXPECT_EQ(scalar_setting(*roi, "x"), "0");
    EXPECT_EQ(scalar_setting(*roi, "y"), "0");
}

TEST(ScenarioEditorV2, UnexposeIsRejectedWhileParentForwardsParameter) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_detector_definition"},
        {"name", "bright"},
        {"value", {
            {"type", "mean_brightness"},
            {"roi", {{"x", "0"}, {"y", "0"}, {"width", "8"}, {"height", "8"}}},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "detector"},
        {"name", "bright"},
        {"setting_path", path({"roi", "x"})},
    });
    auto* detector = find_detector_definition(session.document, "bright");
    ASSERT_NE(detector, nullptr);
    const auto detector_parameter = detector->parameters[0].name;

    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "detect"},
        {"value", {
            {"type", "detected"},
            {"minimum_score", "0.5"},
            {"detector", {{"type", "mean_brightness"}}},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_detector"},
        {"path", path({"definitions", "conditions", "detect", "detector"})},
        {"name", "bright"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "detect"},
        {"setting_path", path({"detector", "roi", "x"})},
    });
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "unexpose_parameter"},
            {"kind", "detector"},
            {"name", "bright"},
            {"setting_path", path({"roi", "x"})},
        }),
        ScenarioEditorError
    );
    EXPECT_TRUE(
        find_detector_definition(session.document, "bright")
            ->detector.find("roi")->find("x")->is_parameter_reference()
    );

    apply_editor_command(session, nlohmann::json{
        {"type", "unexpose_parameter"},
        {"kind", "condition"},
        {"name", "detect"},
        {"setting_path", path({"detector", "roi", "x"})},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "unexpose_parameter"},
        {"kind", "detector"},
        {"name", "bright"},
        {"setting_path", path({"roi", "x"})},
    });
    detector = find_detector_definition(session.document, "bright");
    ASSERT_NE(detector, nullptr);
    EXPECT_TRUE(detector->parameters.empty());
    EXPECT_EQ(scalar_setting(*detector->detector.find("roi"), "x"), "0");
}

TEST(ScenarioEditorV2, ExposesNestedConditionParameter) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "child"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "child"},
        {"setting_path", path({"duration"})},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "parent"},
        {"value", {
            {"type", "all"},
            {"conditions", nlohmann::json::array({
                {{"type", "elapsed"}, {"duration", "1s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"definitions", "conditions", "parent", "conditions", 0})},
        {"name", "child"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "parent"},
        {"setting_path", path({"conditions", 0, "duration"})},
    });

    auto* parent = find_condition_definition(session.document, "parent");
    ASSERT_NE(parent, nullptr);
    ASSERT_EQ(parent->parameters.size(), 1U);
    const auto* child_use = parent->condition.find("conditions")->find_index(0);
    ASSERT_NE(child_use, nullptr);
    const auto* with = child_use->find("with");
    ASSERT_NE(with, nullptr);
    const auto* child = find_condition_definition(session.document, "child");
    ASSERT_NE(child, nullptr);
    ASSERT_EQ(child->parameters.size(), 1U);
    ASSERT_NE(with->find(child->parameters[0].name), nullptr);
    EXPECT_TRUE(with->find(child->parameters[0].name)->is_parameter_reference());

    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "parent"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage_setting"},
        {"path", path({"start_condition"})},
        {"setting_path", path({"conditions", 0, "duration"})},
        {"value", "4s"},
    });
    const auto resolved = resolved_condition(
        session.document,
        session.document.start_condition->value
    );
    EXPECT_EQ(
        scalar_setting(require_condition(resolved, 0), "duration"),
        "4s"
    );

    const auto state = editor_state_json(session);
    const auto usages = state["document"]["condition_usages"];
    const auto nested_usage = std::find_if(
        usages.begin(),
        usages.end(),
        [&](const auto& item) {
            return item["path"] == path({
                "definitions", "conditions", "parent", "conditions", 0
            });
        }
    );
    ASSERT_NE(nested_usage, usages.end());
    EXPECT_EQ((*nested_usage)["name"], "child");
    EXPECT_TRUE((*nested_usage)["overrides"].empty());
    EXPECT_EQ((*nested_usage)["resolved"]["duration"], "1s");
    const auto start_usage = std::find_if(
        usages.begin(),
        usages.end(),
        [&](const auto& item) {
            return item["path"] == path({"start_condition"});
        }
    );
    ASSERT_NE(start_usage, usages.end());
    ASSERT_EQ((*start_usage)["overrides"].size(), 1U);
    EXPECT_EQ(
        (*start_usage)["overrides"][0]["path"],
        path({"conditions", 0, "duration"})
    );
    EXPECT_EQ((*start_usage)["overrides"][0]["default"], "1s");
    EXPECT_EQ((*start_usage)["overrides"][0]["value"], "4s");
}

TEST(ScenarioEditorV2, EditorStateResolvesNestedSharedConditionInsideAny) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "child"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "child"},
        {"setting_path", path({"duration"})},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "parent"},
        {"value", {
            {"type", "any"},
            {"conditions", nlohmann::json::array({
                {{"type", "elapsed"}, {"duration", "1s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"definitions", "conditions", "parent", "conditions", 0})},
        {"name", "child"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "parent"},
        {"setting_path", path({"conditions", 0, "duration"})},
    });

    const auto state = editor_state_json(session);
    const auto usages = state["document"]["condition_usages"];
    const auto usage = std::find_if(
        usages.begin(),
        usages.end(),
        [&](const auto& item) {
            return item["path"] == path({
                "definitions", "conditions", "parent", "conditions", 0
            });
        }
    );
    ASSERT_NE(usage, usages.end());
    EXPECT_EQ((*usage)["resolved"]["duration"], "1s");
    EXPECT_TRUE((*usage)["overrides"].empty());
}

TEST(ScenarioEditorV2, AppendingConditionWithoutIndexKeepsEditorStateValid) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "set_value"},
        {"path", path({"start_condition"})},
        {"value", {
            {"type", "then"},
            {"conditions", nlohmann::json::array({
                {{"type", "elapsed"}, {"duration", "1s"}},
                {{"type", "elapsed"}, {"duration", "2s"}},
                {{"type", "elapsed"}, {"duration", "3s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "add_condition"},
        {"path", path({"start_condition"})},
        {"value", {{"type", "elapsed"}, {"duration", "4s"}}},
    });
    const auto& conditions = session.document.start_condition->value
        .find("conditions")->sequence;
    ASSERT_EQ(conditions.size(), 4U);
    EXPECT_EQ(conditions.back().find("duration")->scalar, "4s");
    EXPECT_NO_THROW((void)editor_state_json(session));
}

TEST(ScenarioEditorV2, NestedSharedConditionUsageUpdatesChildWith) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "child"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_value"},
        {"path", path({"start_condition"})},
        {"value", {
            {"type", "then"},
            {"conditions", nlohmann::json::array({
                {{"use", "child"}},
                {{"type", "elapsed"}, {"duration", "1s"}},
            })},
        }},
    });
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "set_usage_setting"},
            {"path", path({"start_condition", "conditions", 0})},
            {"setting_path", path({"duration"})},
            {"value", "3s"},
        }),
        ScenarioEditorError
    );

    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "child"},
        {"setting_path", path({"duration"})},
    });
    auto* child = find_condition_definition(session.document, "child");
    ASSERT_NE(child, nullptr);
    const auto parameter = child->parameters[0].name;
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage_setting"},
        {"path", path({"start_condition", "conditions", 0})},
        {"setting_path", path({"duration"})},
        {"value", "3s"},
    });
    auto* child_use = session.document.start_condition->value
        .find("conditions")->find_index(0);
    ASSERT_NE(child_use, nullptr);
    const auto* with = child_use->find("with");
    ASSERT_NE(with, nullptr);
    ASSERT_NE(with->find(parameter), nullptr);
    EXPECT_EQ(with->find(parameter)->scalar, "3s");
    const auto resolved = resolved_condition(
        session.document,
        session.document.start_condition->value
    );
    const auto* resolved_child = resolved.find("conditions")->find_index(0);
    ASSERT_NE(resolved_child, nullptr);
    EXPECT_EQ(scalar_setting(*resolved_child, "duration"), "3s");

    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    child_use = session.document.start_condition->value.find("conditions")->find_index(0);
    EXPECT_EQ(child_use->find("with"), nullptr);
    apply_editor_command(session, nlohmann::json{{"type", "redo"}});
    child_use = session.document.start_condition->value.find("conditions")->find_index(0);
    EXPECT_NE(child_use->find("with"), nullptr);
}

TEST(ScenarioEditorV2, DefinitionNestedSharedConditionUsageUpdatesChildWith) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "child"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "child"},
        {"setting_path", path({"duration"})},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "parent"},
        {"value", {
            {"type", "then"},
            {"conditions", nlohmann::json::array({
                {{"type", "elapsed"}, {"duration", "1s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"definitions", "conditions", "parent", "conditions", 0})},
        {"name", "child"},
    });
    auto* child = find_condition_definition(session.document, "child");
    ASSERT_NE(child, nullptr);
    const auto parameter = child->parameters[0].name;
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage_setting"},
        {"path", path({"definitions", "conditions", "parent", "conditions", 0})},
        {"setting_path", path({"duration"})},
        {"value", "4s"},
    });

    auto* parent = find_condition_definition(session.document, "parent");
    ASSERT_NE(parent, nullptr);
    auto* child_use = parent->condition.find("conditions")->find_index(0);
    ASSERT_NE(child_use, nullptr);
    const auto* with = child_use->find("with");
    ASSERT_NE(with, nullptr);
    ASSERT_NE(with->find(parameter), nullptr);
    EXPECT_EQ(with->find(parameter)->scalar, "4s");
    const auto resolved = resolved_condition(
        session.document,
        Value::make_mapping({{"use", Value::make_scalar("parent")}})
    );
    EXPECT_EQ(
        scalar_setting(*resolved.find("conditions")->find_index(0), "duration"),
        "4s"
    );
}

TEST(ScenarioEditorV2, NestedSharedConditionUsageStoresAssetReference) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "child"},
        {"value", {
            {"type", "detected"},
            {"minimum_score", "0.5"},
            {"detector", {
                {"type", "template_match"},
                {"reference", "Asset/YI1.png"},
            }},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "child"},
        {"setting_path", path({"detector", "reference"})},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_value"},
        {"path", path({"start_condition"})},
        {"value", {
            {"type", "then"},
            {"conditions", nlohmann::json::array({
                {{"use", "child"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage_setting"},
        {"path", path({"start_condition", "conditions", 0})},
        {"setting_path", path({"detector", "reference"})},
        {"value", "Asset/DPC.png"},
    });

    const auto resolved = resolved_condition(
        session.document,
        session.document.start_condition->value
    );
    EXPECT_EQ(
        scalar_setting(
            *resolved.find("conditions")->find_index(0)->find("detector"),
            "reference"
        ),
        "Asset/DPC.png"
    );
    const auto state = editor_state_json(session);
    const auto usages = state["document"]["condition_usages"];
    ASSERT_TRUE(usages.is_array());
    const auto usage_path = path({"start_condition", "conditions", 0});
    const auto usage = std::find_if(
        usages.begin(),
        usages.end(),
        [&](const auto& item) { return item["path"] == usage_path; }
    );
    ASSERT_NE(usage, usages.end());
    EXPECT_EQ((*usage)["name"], "child");
    const auto overrides = (*usage)["overrides"];
    ASSERT_EQ(overrides.size(), 1U);
    EXPECT_EQ(overrides[0]["path"], path({"detector", "reference"}));
    EXPECT_EQ(overrides[0]["default"], "Asset/YI1.png");
    EXPECT_EQ(overrides[0]["value"], "Asset/DPC.png");
    const auto exported = export_scenario_yaml(session.document);
    const auto reloaded = import_scenario_yaml(exported);
    ASSERT_TRUE(reloaded.start_condition);
    const auto reloaded_resolved = resolved_condition(
        reloaded,
        reloaded.start_condition->value
    );
    EXPECT_EQ(
        scalar_setting(
            *reloaded_resolved.find("conditions")->find_index(0)->find("detector"),
            "reference"
        ),
        "Asset/DPC.png"
    );
}

TEST(ScenarioEditorV2, RenameConditionDefinitionUpdatesAllUsagesAndUndo) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "wait"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "wait"},
    });
    apply_editor_command(session, nlohmann::json{{"type", "add_split"}, {"index", 0}});
    apply_editor_command(session, nlohmann::json{{"type", "add_rule"}, {"split", 0}});
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"splits", 0, "rules", 0, "condition"})},
        {"name", "wait"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "rename_condition_definition"},
        {"from", "wait"},
        {"to", "delay"},
    });
    EXPECT_EQ(session.document.start_condition->use_name(), "delay");
    EXPECT_EQ(
        session.document.splits[0]->rules[0].rule.condition.use_name(),
        "delay"
    );

    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_EQ(session.document.start_condition->use_name(), "wait");
    EXPECT_EQ(
        session.document.splits[0]->rules[0].rule.condition.use_name(),
        "wait"
    );
    apply_editor_command(session, nlohmann::json{{"type", "redo"}});
    EXPECT_EQ(session.document.start_condition->use_name(), "delay");
    EXPECT_EQ(
        session.document.splits[0]->rules[0].rule.condition.use_name(),
        "delay"
    );
}

TEST(ScenarioEditorV2, RenameDetectorDefinitionUpdatesAllUsagesAndUndo) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_detector_definition"},
        {"name", "bright"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "detect"},
        {"value", {
            {"type", "detected"},
            {"minimum_score", "0.5"},
            {"detector", {{"type", "mean_brightness"}}},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_detector"},
        {"path", path({"definitions", "conditions", "detect", "detector"})},
        {"name", "bright"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_value"},
        {"path", path({"start_condition"})},
        {"value", {
            {"type", "detected"},
            {"minimum_score", "0.5"},
            {"detector", {{"use", "bright"}}},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "rename_detector_definition"},
        {"from", "bright"},
        {"to", "luma"},
    });

    const auto* definition = find_condition_definition(session.document, "detect");
    ASSERT_NE(definition, nullptr);
    EXPECT_EQ(definition->condition.find("detector")->find("use")->scalar, "luma");
    EXPECT_EQ(
        session.document.start_condition->value.find("detector")->find("use")->scalar,
        "luma"
    );
    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    definition = find_condition_definition(session.document, "detect");
    ASSERT_NE(definition, nullptr);
    EXPECT_EQ(definition->condition.find("detector")->find("use")->scalar, "bright");
    EXPECT_EQ(
        session.document.start_condition->value.find("detector")->find("use")->scalar,
        "bright"
    );
    apply_editor_command(session, nlohmann::json{{"type", "redo"}});
    definition = find_condition_definition(session.document, "detect");
    ASSERT_NE(definition, nullptr);
    EXPECT_EQ(definition->condition.find("detector")->find("use")->scalar, "luma");
}

TEST(ScenarioEditorV2, ExtractConditionDefinitionMovesInlineRuleCondition) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{{"type", "add_split"}, {"index", 0}});
    apply_editor_command(session, nlohmann::json{{"type", "add_rule"}, {"split", 0}});
    apply_editor_command(session, nlohmann::json{
        {"type", "extract_condition_definition"},
        {"path", path({"splits", 0, "rules", 0, "condition"})},
        {"name", "extracted"},
    });

    auto* definition = find_condition_definition(session.document, "extracted");
    ASSERT_NE(definition, nullptr);
    EXPECT_TRUE(definition->parameters.empty());
    ASSERT_NE(definition->condition.find("type"), nullptr);
    EXPECT_EQ(definition->condition.find("type")->scalar, "elapsed");
    const auto& rule = session.document.splits[0]->rules[0].rule;
    EXPECT_TRUE(rule.condition.is_shared_use());
    EXPECT_EQ(rule.condition.use_name(), "extracted");

    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_EQ(find_condition_definition(session.document, "extracted"), nullptr);
    EXPECT_FALSE(session.document.splits[0]->rules[0].rule.condition.is_shared_use());
    apply_editor_command(session, nlohmann::json{{"type", "redo"}});
    EXPECT_NE(find_condition_definition(session.document, "extracted"), nullptr);
    EXPECT_TRUE(session.document.splits[0]->rules[0].rule.condition.is_shared_use());
}

TEST(ScenarioEditorV2, ExtractConditionDefinitionMovesNestedChild) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "set_value"},
        {"path", path({"start_condition"})},
        {"value", {
            {"type", "then"},
            {"conditions", nlohmann::json::array({
                {{"type", "detected"}, {"minimum_score", "0.9"},
                 {"detector", {{"type", "mean_brightness"}}}},
                {{"type", "elapsed"}, {"duration", "1s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "extract_condition_definition"},
        {"path", path({"start_condition", "conditions", 0})},
        {"name", "child_condition"},
    });

    auto* definition = find_condition_definition(session.document, "child_condition");
    ASSERT_NE(definition, nullptr);
    EXPECT_EQ(definition->condition.find("type")->scalar, "detected");
    const auto& start_conditions = session.document.start_condition->value
        .find("conditions")->sequence;
    ASSERT_EQ(start_conditions.size(), 2U);
    ASSERT_NE(start_conditions[0].find("use"), nullptr);
    EXPECT_EQ(start_conditions[0].find("use")->scalar, "child_condition");
    EXPECT_EQ(start_conditions[1].find("type")->scalar, "elapsed");
}

TEST(ScenarioEditorV2, ExtractConditionDefinitionSupportsSequenceStep) {
    EditorSession session;
    session.document = import_scenario_yaml(R"(
schema_version: 2
start_condition: {type: elapsed, duration: 1s}
splits:
  - rules:
      - sequence:
          - condition: {type: elapsed, duration: 2s}
            action: split
)");
    apply_editor_command(session, nlohmann::json{
        {"type", "extract_condition_definition"},
        {"path", path({"splits", 0, "rules", 0, "sequence", 0, "condition"})},
        {"name", "sequence_condition"},
    });

    auto* definition = find_condition_definition(session.document, "sequence_condition");
    ASSERT_NE(definition, nullptr);
    EXPECT_EQ(definition->condition.find("type")->scalar, "elapsed");
    const auto& step = session.document.splits[0]->rules[0].sequence_rules[0];
    EXPECT_TRUE(step.condition.is_shared_use());
    EXPECT_EQ(step.condition.use_name(), "sequence_condition");

    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_EQ(find_condition_definition(session.document, "sequence_condition"), nullptr);
    EXPECT_FALSE(
        session.document.splits[0]->rules[0].sequence_rules[0]
            .condition.is_shared_use()
    );
}

TEST(ScenarioEditorV2, ExtractConditionDefinitionRejectsSharedAndParameterizedConditions) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "wait"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "wait"},
    });
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "extract_condition_definition"},
            {"path", path({"start_condition"})},
            {"name", "copy"},
        }),
        ScenarioEditorError
    );

    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "parent"},
        {"value", {
            {"type", "then"},
            {"conditions", nlohmann::json::array({
                {{"type", "elapsed"}, {"duration", "1s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "parent"},
        {"setting_path", path({"conditions", 0, "duration"})},
    });
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "extract_condition_definition"},
            {"path", path({"definitions", "conditions", "parent", "conditions", 0})},
            {"name", "child"},
        }),
        ScenarioEditorError
    );
}

TEST(ScenarioEditorV2, MoveSplitReordersWholeSplitAndUndoRedo) {
    EditorSession session;
    session.document = import_scenario_yaml(R"(
schema_version: 2
start_condition: {type: elapsed, duration: 1s}
splits:
  - rules:
      - condition: {type: elapsed, duration: 1s}
        action: split
  - rules:
      - condition: {type: elapsed, duration: 2s}
        action: skip
  - null
)");
    apply_editor_command(session, nlohmann::json{
        {"type", "move_split"},
        {"from", 2},
        {"to", 0},
    });
    ASSERT_EQ(session.document.splits.size(), 3U);
    EXPECT_FALSE(session.document.splits[0].has_value());
    ASSERT_TRUE(session.document.splits[1]->rules[0].rule.condition.value
        .find("duration"));
    EXPECT_EQ(
        session.document.splits[1]->rules[0].rule.condition.value
            .find("duration")->scalar,
        "1s"
    );
    EXPECT_EQ(
        session.document.splits[2]->rules[0].rule.condition.value
            .find("duration")->scalar,
        "2s"
    );

    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_TRUE(session.document.splits[2] == std::nullopt);
    apply_editor_command(session, nlohmann::json{{"type", "redo"}});
    EXPECT_TRUE(session.document.splits[0] == std::nullopt);

    TemporaryDirectory directory;
    const auto path = directory.path() / "ordered.yaml";
    save_scenario_document(session.document, path);
    const auto reloaded = load_scenario_document(path);
    ASSERT_EQ(reloaded.splits.size(), 3U);
    EXPECT_FALSE(reloaded.splits[0].has_value());
    EXPECT_EQ(
        reloaded.splits[1]->rules[0].rule.condition.value.find("duration")->scalar,
        "1s"
    );

    apply_editor_command(session, nlohmann::json{
        {"type", "move_split"},
        {"from", 0},
        {"to", 2},
    });
    EXPECT_FALSE(session.document.splits[2].has_value());
    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_FALSE(session.document.splits[0].has_value());
}

TEST(ScenarioEditorV2, InlineConditionExpandsOnlyOneLevelAndPreservesNestedUses) {
    EditorSession session;
    session.document = import_scenario_yaml(R"(
schema_version: 2
definitions:
  detectors:
    detector_image:
      parameters:
        image: Asset/YI1.png
      detector:
        type: template_match
        reference: {param: image}
  conditions:
    course_name:
      parameters:
        image: Asset/default.png
      condition:
        type: detected
        minimum_score: 0.9
        detector:
          use: detector_image
          with:
            image: {param: image}
    sp_even:
      parameters:
        course_image: Asset/YI1.png
      condition:
        type: then
        conditions:
          - type: elapsed
            duration: 1s
          - use: course_name
            with:
              image: {param: course_image}
start_condition:
  use: sp_even
  with:
    course_image: Asset/DPC.png
splits: []
)");
    const auto before = value_to_json(resolved_condition(
        session.document,
        session.document.start_condition->value
    ));
    apply_editor_command(session, nlohmann::json{
        {"type", "inline_condition"},
        {"path", path({"start_condition"})},
    });

    const auto& inlined = session.document.start_condition->value;
    EXPECT_FALSE(session.document.start_condition->is_shared_use());
    EXPECT_EQ(inlined.find("type")->scalar, "then");
    const auto* conditions = inlined.find("conditions");
    ASSERT_NE(conditions, nullptr);
    ASSERT_EQ(conditions->sequence.size(), 2U);
    const auto& child_use = conditions->sequence[1];
    EXPECT_EQ(child_use.find("use")->scalar, "course_name");
    EXPECT_EQ(
        child_use.find("with")->find("image")->scalar,
        "Asset/DPC.png"
    );
    auto* child = find_condition_definition(session.document, "course_name");
    ASSERT_NE(child, nullptr);
    EXPECT_EQ(child->condition.find("detector")->find("use")->scalar, "detector_image");
    auto* parent = find_condition_definition(session.document, "sp_even");
    ASSERT_NE(parent, nullptr);
    EXPECT_TRUE(
        parent->condition.find("conditions")->find_index(1)->find("with")
            ->find("image")->is_parameter_reference()
    );
    EXPECT_EQ(
        value_to_json(resolved_condition(
            session.document,
            session.document.start_condition->value
        )),
        before
    );

    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_TRUE(session.document.start_condition->is_shared_use());
    EXPECT_EQ(session.document.start_condition->use_name(), "sp_even");
    apply_editor_command(session, nlohmann::json{{"type", "redo"}});
    EXPECT_FALSE(session.document.start_condition->is_shared_use());

    const auto exported = export_scenario_yaml(session.document);
    const auto reloaded = import_scenario_yaml(exported);
    const auto* reloaded_child_use = reloaded.start_condition->value
        .find("conditions")->find_index(1);
    ASSERT_NE(reloaded_child_use, nullptr);
    EXPECT_EQ(reloaded_child_use->find("use")->scalar, "course_name");
    EXPECT_EQ(
        value_to_json(resolved_condition(reloaded, reloaded.start_condition->value)),
        before
    );
}

TEST(ScenarioEditorV2, InlineConditionPreservesThreeNestedConditionLevels) {
    EditorSession session;
    session.document = import_scenario_yaml(R"(
schema_version: 2
definitions:
  conditions:
    leaf:
      condition: {type: elapsed, duration: 2s}
    mid:
      condition:
        type: then
        conditions:
          - use: leaf
    top:
      condition:
        type: then
        conditions:
          - use: mid
start_condition:
  use: top
splits: []
)");
    const auto before = value_to_json(resolved_condition(
        session.document,
        session.document.start_condition->value
    ));
    apply_editor_command(session, nlohmann::json{
        {"type", "inline_condition"},
        {"path", path({"start_condition"})},
    });
    const auto& inlined = session.document.start_condition->value;
    EXPECT_EQ(inlined.find("type")->scalar, "then");
    const auto& nested = inlined.find("conditions")->sequence[0];
    EXPECT_EQ(nested.find("use")->scalar, "mid");
    EXPECT_EQ(
        value_to_json(resolved_condition(
            session.document,
            session.document.start_condition->value
        )),
        before
    );
}

TEST(ScenarioEditorV2, InlineConditionUsesParameterDefaultsAndOmittedNull) {
    EditorSession session;
    session.document = import_scenario_yaml(R"(
schema_version: 2
definitions:
  conditions:
    defaulted:
      parameters:
        within_value: 2s
      condition:
        type: then
        within: {param: within_value}
        conditions:
          - type: elapsed
            duration: 1s
    omitted:
      parameters:
        within_value: null
      condition:
        type: then
        within: {param: within_value}
        conditions:
          - type: elapsed
            duration: 1s
start_condition:
  use: defaulted
splits: []
)");
    apply_editor_command(session, nlohmann::json{
        {"type", "inline_condition"},
        {"path", path({"start_condition"})},
    });
    EXPECT_EQ(
        session.document.start_condition->value.find("within")->scalar,
        "2s"
    );

    apply_editor_command(session, nlohmann::json{
        {"type", "set_value"},
        {"path", path({"start_condition"})},
        {"value", {{"use", "omitted"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "inline_condition"},
        {"path", path({"start_condition"})},
    });
    EXPECT_EQ(session.document.start_condition->value.find("within"), nullptr);
    EXPECT_EQ(session.document.start_condition->value.find("type")->scalar, "then");
}

TEST(ScenarioEditorV2, RenameAndDetachUpdateReferences) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "wait"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "wait"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "rename_condition_definition"},
        {"from", "wait"},
        {"to", "delay"},
    });
    EXPECT_EQ(session.document.start_condition->use_name(), "delay");
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "delete_condition_definition"},
            {"name", "delay"},
        }),
        ScenarioEditorError
    );
    apply_editor_command(session, nlohmann::json{
        {"type", "inline_condition"},
        {"path", path({"start_condition"})},
    });
    EXPECT_FALSE(session.document.start_condition->is_shared_use());
    apply_editor_command(session, nlohmann::json{
        {"type", "delete_condition_definition"},
        {"name", "delay"},
    });
    EXPECT_TRUE(session.document.definitions.conditions.empty());
}

TEST(ScenarioEditorV2, RejectsUnknownFieldsAndLegacyYaml) {
    EditorSession session = new_editor_session();
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "set_setting"},
            {"path", path({"start_condition"})},
            {"key", "unknown"},
            {"value", "1"},
        }),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
start_condition: {type: elapsed, duration: 1s}
splits: []
)"),
        ScenarioEditorError
    );
}

TEST(ScenarioEditorV2, RoundTripKeepsExtraRootAndQuotedScalars) {
    const auto document = import_scenario_yaml(R"(
schema_version: 2
metadata:
  title: My Scenario
  note: "null"
start_condition:
  type: detected
  minimum_score: 0.5
  detector:
    type: template_match
    reference: "null"
splits: []
)");
    ASSERT_EQ(document.extra_root.size(), 1U);
    const auto exported = export_scenario_yaml(document);
    const auto reloaded = import_scenario_yaml(exported);
    ASSERT_EQ(reloaded.extra_root.size(), 1U);
    EXPECT_EQ(reloaded.extra_root[0].first, "metadata");
    const auto& metadata = reloaded.extra_root[0].second;
    EXPECT_EQ(scalar_setting(metadata, "title"), "My Scenario");
    EXPECT_EQ(scalar_setting(metadata, "note"), "null");
    ASSERT_TRUE(reloaded.start_condition);
    const auto& detector = require_setting(reloaded.start_condition->value, "detector");
    EXPECT_EQ(scalar_setting(detector, "reference"), "null");
}

TEST(ScenarioEditorV2, SaveValidatesAndKeepsOriginalFileOnFailure) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    const std::string original = R"(
schema_version: 2
start_condition: {type: elapsed, duration: 1s}
splits: []
)";
    write_text(path, original);
    auto document = import_scenario_yaml(original);
    save_scenario_document(document, path);
    EXPECT_EQ(read_text(path), export_scenario_yaml(document));
    (void)load_scenario(path);

    document.start_condition->value.set("type", Value::make_scalar("unsupported"));
    EXPECT_THROW(save_scenario_document(document, path), ScenarioEditorError);
    EXPECT_EQ(read_text(path), export_scenario_yaml(import_scenario_yaml(original)));
}

TEST(ScenarioEditorV2, JsonStateExposesDefinitionsParametersAndResolvedValues) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "wait"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "wait"},
    });
    const auto state = editor_state_json(session);
    EXPECT_EQ(state["version"], 3);
    ASSERT_TRUE(state["document"]["definitions"]["conditions"].is_array());
    EXPECT_EQ(state["document"]["definitions"]["conditions"][0]["name"], "wait");
    EXPECT_EQ(state["document"]["start_condition"]["use"], "wait");
    EXPECT_EQ(state["document"]["start_condition_resolved"]["type"], "elapsed");
    EXPECT_TRUE(state["schema"]["conditionFields"].contains("elapsed"));
}

TEST(ScenarioEditorV2, ExposureIsOneUndoStep) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "wait"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "wait"},
    });
    const std::size_t undo_before = session.undo_stack.size();
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "wait"},
        {"setting_path", path({"duration"})},
    });
    EXPECT_EQ(session.undo_stack.size(), undo_before + 1);
    EXPECT_EQ(find_condition_definition(session.document, "wait")->parameters.size(), 1U);
    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_TRUE(find_condition_definition(session.document, "wait")->parameters.empty());
    EXPECT_FALSE(
        find_condition_definition(session.document, "wait")->condition.find("duration")
            ->is_parameter_reference()
    );
    apply_editor_command(session, nlohmann::json{{"type", "redo"}});
    EXPECT_EQ(find_condition_definition(session.document, "wait")->parameters.size(), 1U);
}
TEST(ScenarioEditorV2, RejectsUsageChangeForUnexposedSetting) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "wait"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "wait"},
    });
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "set_usage_setting"},
            {"path", path({"start_condition"})},
            {"setting_path", path({"duration"})},
            {"value", "2s"},
        }),
        ScenarioEditorError
    );
    EXPECT_EQ(session.undo_stack.size(), 2U);
    EXPECT_EQ(session.document.start_condition->with(), nullptr);
    EXPECT_TRUE(find_condition_definition(session.document, "wait")->parameters.empty());
}

TEST(ScenarioEditorV2, RejectsMismatchedParameterValues) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "wait"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "wait"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "wait"},
        {"setting_path", path({"duration"})},
    });
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "set_usage_setting"},
            {"path", path({"start_condition"})},
            {"setting_path", path({"duration"})},
            {"value", {{"not", "a duration"}}},
        }),
        ScenarioEditorError
    );
    EXPECT_EQ(session.undo_stack.size(), 3U);
    EXPECT_EQ(session.document.start_condition->with(), nullptr);
}

TEST(ScenarioEditorV2, RemovesOptionalDefinitionFields) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "sequence"},
        {"value", {
            {"type", "then"},
            {"within", "2s"},
            {"conditions", nlohmann::json::array({
                {{"type", "elapsed"}, {"duration", "1s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "remove_definition_setting"},
        {"kind", "condition"},
        {"name", "sequence"},
        {"setting_path", path({"within"})},
    });
    const auto* definition = find_condition_definition(session.document, "sequence");
    ASSERT_NE(definition, nullptr);
    EXPECT_EQ(definition->condition.find("within"), nullptr);
}

TEST(ScenarioEditorV2, AddsMissingOptionalFieldsToInlineAndDefinitionConditions) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "set_condition_type"},
        {"path", path({"start_condition"})},
        {"value", "then"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_value"},
        {"path", path({"start_condition", "within"})},
        {"value", "3s"},
    });
    EXPECT_EQ(
        scalar_setting(session.document.start_condition->value, "within"),
        "3s"
    );

    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "sequence"},
        {"value", {
            {"type", "then"},
            {"conditions", nlohmann::json::array({
                {{"type", "elapsed"}, {"duration", "1s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_definition_setting"},
        {"kind", "condition"},
        {"name", "sequence"},
        {"setting_path", path({"within"})},
        {"value", "2s"},
    });
    const auto* definition = find_condition_definition(session.document, "sequence");
    ASSERT_NE(definition, nullptr);
    EXPECT_EQ(scalar_setting(definition->condition, "within"), "2s");
}

TEST(ScenarioEditorV2, OptionalExposureUsesAnOmittedDefault) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_condition_definition"},
        {"name", "sequence"},
        {"value", {
            {"type", "then"},
            {"conditions", nlohmann::json::array({
                {{"type", "elapsed"}, {"duration", "1s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_definition_setting"},
        {"kind", "condition"},
        {"name", "sequence"},
        {"setting_path", path({"within"})},
        {"value", "2s"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "expose_parameter"},
        {"kind", "condition"},
        {"name", "sequence"},
        {"setting_path", path({"within"})},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_definition_setting"},
        {"kind", "condition"},
        {"name", "sequence"},
        {"setting_path", path({"within"})},
        {"value", nullptr},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"start_condition"})},
        {"name", "sequence"},
    });
    apply_editor_command(session, nlohmann::json{{"type", "add_split"}, {"index", 0}});
    apply_editor_command(session, nlohmann::json{{"type", "add_rule"}, {"split", 0}});
    apply_editor_command(session, nlohmann::json{
        {"type", "use_condition"},
        {"path", path({"splits", 0, "rules", 0, "condition"})},
        {"name", "sequence"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage_setting"},
        {"path", path({"start_condition"})},
        {"setting_path", path({"within"})},
        {"value", "3s"},
    });

    auto* definition = find_condition_definition(session.document, "sequence");
    ASSERT_NE(definition, nullptr);
    ASSERT_EQ(definition->parameters.size(), 1U);
    EXPECT_TRUE(definition->parameters[0].default_value.is_null());
    EXPECT_TRUE(definition->condition.find("within")->is_parameter_reference());

    const auto start = resolved_condition(session.document, session.document.start_condition->value);
    EXPECT_EQ(scalar_setting(start, "within"), "3s");
    const auto unbound = resolved_condition(
        session.document,
        session.document.splits[0]->rules[0].rule.condition.value
    );
    EXPECT_EQ(unbound.find("within"), nullptr);

    apply_editor_command(session, nlohmann::json{
        {"type", "reset_usage_setting"},
        {"path", path({"start_condition"})},
        {"setting_path", path({"within"})},
    });
    EXPECT_EQ(
        resolved_condition(session.document, session.document.start_condition->value)
            .find("within"),
        nullptr
    );
}

TEST(ScenarioEditorV2, RoundTripKeepsExplicitExposureAndNestedForwarding) {
    const std::string source = R"(
schema_version: 2
definitions:
  detectors:
    course_name_detector:
      parameters:
        image: Asset/YI1.png
      detector:
        type: root_mean_square_similarity
        reference: {param: image}
  conditions:
    course_name_condition:
      parameters:
        image: Asset/YI1.png
      condition:
        type: detected
        minimum_score: 0.9
        detector:
          use: course_name_detector
          with:
            image: {param: image}
start_condition:
  use: course_name_condition
  with:
    image: Asset/DPC.png
splits: []
)";
    auto document = import_scenario_yaml(source);
    const auto exported = export_scenario_yaml(document);
    const auto reloaded = import_scenario_yaml(exported);

    const auto* condition = find_condition_definition(reloaded, "course_name_condition");
    ASSERT_NE(condition, nullptr);
    ASSERT_EQ(condition->parameters.size(), 1U);
    EXPECT_EQ(condition->parameters[0].name, "image");
    const auto* detector_use = condition->condition.find("detector");
    ASSERT_NE(detector_use, nullptr);
    const auto* with = detector_use->find("with");
    ASSERT_NE(with, nullptr);
    ASSERT_NE(with->find("image"), nullptr);
    EXPECT_TRUE(with->find("image")->is_parameter_reference());

    const auto resolved = resolved_condition(
        reloaded,
        reloaded.start_condition->value
    );
    const auto* detector = resolved.find("detector");
    ASSERT_NE(detector, nullptr);
    EXPECT_EQ(detector->find("reference")->scalar, "Asset/DPC.png");
}
