#include <gtest/gtest.h>

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

TEST(ScenarioEditorV2, ExportsV2AndRuntimeLoaderReadsIt) {
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
    EXPECT_NE(exported.find("schema_version: 2"), std::string::npos) << exported;
    EXPECT_NE(exported.find("use: wait"), std::string::npos) << exported;
    EXPECT_NE(exported.find("param: duration"), std::string::npos) << exported;

    const auto reloaded = import_scenario_yaml(exported);
    EXPECT_EQ(reloaded.definitions.conditions.size(), 1U);
    const auto loaded = load_scenario(path);
    const auto* start = dynamic_cast<const ElapsedCondition*>(
        loaded.scenario.start_condition.get()
    );
    ASSERT_NE(start, nullptr);
    EXPECT_EQ(start->duration(), std::chrono::seconds{3});
}

TEST(ScenarioEditorV2, PerUsageSettingGeneratesParametersAndResetReverts) {
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
        {"type", "set_usage_setting"},
        {"path", path({"start_condition"})},
        {"setting_path", path({"duration"})},
        {"value", "2s"},
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

TEST(ScenarioEditorV2, SharedDetectorDefinitionsAndPerUseValuesWork) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "create_detector_definition"},
        {"name", "bright"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_setting"},
        {"path", path({"definitions", "detectors", "bright"})},
        {"key", "roi"},
        {"value", {{"x", "0"}, {"y", "0"}, {"width", "8"}, {"height", "8"}}},
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
        {"type", "set_detector_usage_setting"},
        {"path", path({"definitions", "conditions", "detect", "detector"})},
        {"setting_path", path({"roi", "x"})},
        {"value", "2"},
    });
    const auto resolved = scenario::v2::resolve_condition(
        session.document.definitions,
        Value::make_mapping({{"use", Value::make_scalar("detect")}})
    );
    const auto* detector = resolved.find("detector");
    ASSERT_NE(detector, nullptr);
    const auto* roi = detector->find("roi");
    ASSERT_NE(roi, nullptr);
    EXPECT_EQ(scalar_setting(*roi, "x"), "2");
    const auto* definition = find_detector_definition(session.document, "bright");
    ASSERT_NE(definition, nullptr);
    ASSERT_EQ(definition->parameters.size(), 1U);
    EXPECT_TRUE(definition->detector.find("roi")->find("x")->is_parameter_reference());
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
    EXPECT_NE(exported.find("metadata:"), std::string::npos) << exported;
    EXPECT_NE(exported.find("reference: \"null\""), std::string::npos) << exported;
    const auto reloaded = import_scenario_yaml(exported);
    ASSERT_EQ(reloaded.extra_root.size(), 1U);
    const auto& metadata = reloaded.extra_root[0].second;
    EXPECT_EQ(scalar_setting(metadata, "title"), "My Scenario");
    const auto* note = metadata.find("note");
    ASSERT_NE(note, nullptr);
    EXPECT_TRUE(note->is_scalar());
    EXPECT_TRUE(note->quoted);
    const auto* reference =
        reloaded.start_condition->value.find("detector")->find("reference");
    ASSERT_NE(reference, nullptr);
    EXPECT_TRUE(reference->is_scalar());
    EXPECT_TRUE(reference->quoted);
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

TEST(ScenarioEditorV2, ParameterGenerationIsOneUndoStep) {
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
        {"type", "set_usage_setting"},
        {"path", path({"start_condition"})},
        {"setting_path", path({"duration"})},
        {"value", "2s"},
    });
    EXPECT_EQ(session.undo_stack.size(), undo_before + 1);
    EXPECT_EQ(find_condition_definition(session.document, "wait")->parameters.size(), 1U);
    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_TRUE(find_condition_definition(session.document, "wait")->parameters.empty());
    EXPECT_EQ(session.document.start_condition->with(), nullptr);
    EXPECT_FALSE(
        find_condition_definition(session.document, "wait")->condition.find("duration")
            ->is_parameter_reference()
    );
    apply_editor_command(session, nlohmann::json{{"type", "redo"}});
    EXPECT_EQ(find_condition_definition(session.document, "wait")->parameters.size(), 1U);
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
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "set_usage_setting"},
            {"path", path({"start_condition"})},
            {"setting_path", path({"duration"})},
            {"value", {{"not", "a duration"}}},
        }),
        ScenarioEditorError
    );
    EXPECT_EQ(session.undo_stack.size(), 2U);
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

TEST(ScenarioEditorV2, PerUsageOptionalFieldUsesAnOmittedDefault) {
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

TEST(ScenarioEditorV2, PerUsageOptionalRoiUsesAnOmittedDefault) {
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
        {"type", "set_detector_usage_setting"},
        {"path", path({"definitions", "conditions", "detect", "detector"})},
        {"setting_path", path({"roi"})},
        {"value", {
            {"x", "0"}, {"y", "0"}, {"width", "8"}, {"height", "8"},
        }},
    });
    const auto resolved = resolved_condition(
        session.document,
        Value::make_mapping({{"use", Value::make_scalar("detect")}})
    );
    const auto* detector = resolved.find("detector");
    ASSERT_NE(detector, nullptr);
    ASSERT_NE(detector->find("roi"), nullptr);
    auto* definition = find_detector_definition(session.document, "bright");
    ASSERT_NE(definition, nullptr);
    ASSERT_EQ(definition->parameters.size(), 1U);
    EXPECT_TRUE(definition->parameters[0].default_value.is_null());
    EXPECT_TRUE(definition->detector.find("roi")->is_parameter_reference());

    apply_editor_command(session, nlohmann::json{
        {"type", "reset_detector_usage_setting"},
        {"path", path({"definitions", "conditions", "detect", "detector"})},
        {"setting_path", path({"roi"})},
    });
    const auto reset = resolved_condition(
        session.document,
        Value::make_mapping({{"use", Value::make_scalar("detect")}})
    );
    EXPECT_EQ(reset.find("detector")->find("roi"), nullptr);
}
