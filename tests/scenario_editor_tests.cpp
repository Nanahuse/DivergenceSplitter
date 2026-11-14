#include <gtest/gtest.h>

#include <chrono>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <string>
#include <string_view>

#include "divergencesplitter/condition/conditions.hpp"
#include "divergencesplitter/detector/detector.hpp"
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
            / ("divergencesplitter-editor-" + std::to_string(++counter) + "-"
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

void write_text(const std::filesystem::path& path, std::string_view text) {
    std::ofstream stream{path, std::ios::binary};
    stream << text;
}

std::string read_text(const std::filesystem::path& path) {
    std::ifstream stream{path, std::ios::binary};
    return {std::istreambuf_iterator<char>{stream}, std::istreambuf_iterator<char>{}};
}

}  // namespace

TEST(ScenarioEditor, ImportsAnchorsWithoutResolvingThem) {
    const auto document = import_scenario_yaml(R"(
definitions:
  visible: &visible
    type: detected
    minimum_score: 0.95
    detector:
      type: mean_brightness
start_condition: *visible
splits:
  - rules:
      - condition: *visible
        action: split
)");

    ASSERT_EQ(document.definitions.size(), 1U);
    EXPECT_EQ(document.definitions[0].name, "visible");
    EXPECT_EQ(document.definitions[0].kind, DefinitionKind::condition);
    ASSERT_TRUE(document.start_condition.has_value());
    EXPECT_TRUE(document.start_condition->is_reference());
    EXPECT_EQ(document.start_condition->anchor(), "visible");
    ASSERT_EQ(document.splits.size(), 1U);
    ASSERT_TRUE(document.splits[0].has_value());
    ASSERT_EQ(document.splits[0]->rules.size(), 1U);
    EXPECT_TRUE(document.splits[0]->rules[0].rule.condition.is_reference());

    const auto resolved = resolve_condition(document, document.start_condition->value);
    EXPECT_EQ(scalar_setting(resolved, "type"), "detected");
    EXPECT_EQ(scalar_setting(resolved, "minimum_score"), "0.95");
}

TEST(ScenarioEditor, ExportsSharedAnchorsAndReferencesThatRoundTrip) {
    auto document = import_scenario_yaml(R"(
definitions:
  visible: &visible
    type: detected
    minimum_score: 0.95
    detector:
      type: mean_brightness
start_condition: *visible
splits:
  - rules:
      - condition: *visible
        action: split
)");

    auto& definition = document.definitions.front();
    definition.value.set("minimum_score", Value::make_scalar("0.8"));
    const auto start_resolved = resolve_condition(document, document.start_condition->value);
    EXPECT_EQ(scalar_setting(start_resolved, "minimum_score"), "0.8");
    const auto rule_resolved =
        resolve_condition(document, document.splits[0]->rules[0].rule.condition.value);
    EXPECT_EQ(scalar_setting(rule_resolved, "minimum_score"), "0.8");

    const std::string yaml = export_scenario_yaml(document);
    EXPECT_NE(yaml.find("&visible"), std::string::npos) << yaml;
    EXPECT_NE(yaml.find("*visible"), std::string::npos) << yaml;

    const auto reloaded = import_scenario_yaml(yaml);
    ASSERT_EQ(reloaded.definitions.size(), 1U);
    ASSERT_TRUE(reloaded.start_condition.has_value());
    EXPECT_TRUE(reloaded.start_condition->is_reference());
    EXPECT_EQ(reloaded.start_condition->anchor(), "visible");
    ASSERT_EQ(reloaded.splits.size(), 1U);
    EXPECT_TRUE(reloaded.splits[0]->rules[0].rule.condition.is_reference());
}

TEST(ScenarioEditor, PreservesExtendsAndOverrides) {
    const std::string source = R"(
definitions:
  course_finish: &course_finish
    type: all
    conditions:
      - id: course
        type: elapsed
        duration: 1s
      - id: finish
        type: elapsed
        duration: 2s
start_condition:
  extends: *course_finish
  overrides:
    finish:
      duration: 5s
splits: []
)";
    const auto document = import_scenario_yaml(source);
    ASSERT_TRUE(document.start_condition.has_value());
    EXPECT_TRUE(document.start_condition->is_inheritance());
    EXPECT_EQ(document.start_condition->anchor(), "course_finish");

    const auto resolved = resolve_condition(document, document.start_condition->value);
    EXPECT_EQ(scalar_setting(require_condition(resolved, 0), "duration"), "1s");
    EXPECT_EQ(scalar_setting(require_condition(resolved, 1), "duration"), "5s");

    const std::string yaml = export_scenario_yaml(document);
    EXPECT_NE(yaml.find("extends: *course_finish"), std::string::npos) << yaml;
    EXPECT_NE(yaml.find("overrides:"), std::string::npos) << yaml;

    const auto reloaded = import_scenario_yaml(yaml);
    ASSERT_TRUE(reloaded.start_condition.has_value());
    EXPECT_TRUE(reloaded.start_condition->is_inheritance());
    const auto reloaded_resolved =
        resolve_condition(reloaded, reloaded.start_condition->value);
    EXPECT_EQ(scalar_setting(require_condition(reloaded_resolved, 1), "duration"), "5s");
}

TEST(ScenarioEditor, ExportedYamlLoadsInTheRuntimeLoader) {
    const auto document = import_scenario_yaml(R"(
definitions:
  course_finish: &course_finish
    type: all
    conditions:
      - id: course
        type: elapsed
        duration: 1s
      - id: finish
        type: elapsed
        duration: 2s
start_condition:
  extends: *course_finish
  overrides:
    finish:
      duration: 5s
splits:
  - rules:
      - condition: *course_finish
        action: split
)");

    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    write_text(path, export_scenario_yaml(document));

    const auto loaded = load_scenario(path);
    const auto* start = dynamic_cast<const AllCondition*>(loaded.scenario.start_condition.get());
    ASSERT_NE(start, nullptr);
    ASSERT_EQ(start->children().size(), 2U);
    const auto* course = dynamic_cast<const ElapsedCondition*>(start->children()[0]);
    const auto* finish = dynamic_cast<const ElapsedCondition*>(start->children()[1]);
    ASSERT_NE(course, nullptr);
    ASSERT_NE(finish, nullptr);
    EXPECT_EQ(course->duration(), std::chrono::seconds{1});
    EXPECT_EQ(finish->duration(), std::chrono::seconds{5});
    ASSERT_EQ(loaded.scenario.splits.size(), 1U);
    ASSERT_TRUE(loaded.scenario.splits[0].has_value());
    ASSERT_EQ(loaded.scenario.splits[0]->size(), 1U);
    EXPECT_NE(dynamic_cast<const AllCondition*>(loaded.scenario.splits[0]->at(0)->active_condition()), nullptr);
}

TEST(ScenarioEditor, CommandsEditSharedConditionsAndUndoRedo) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "set_definition"},
        {"name", "course_finish"},
        {"value", {
            {"type", "all"},
            {"conditions", nlohmann::json::array({
                {{"id", "course"}, {"type", "elapsed"}, {"duration", "1s"}},
                {{"id", "finish"}, {"type", "elapsed"}, {"duration", "2s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "add_split"},
        {"index", 0},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "add_rule"},
        {"split", 0},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage"},
        {"path", nlohmann::json::array({"splits", 0, "rules", 0, "condition"})},
        {"mode", "reference"},
        {"anchor", "course_finish"},
    });

    const auto resolved_rule = [&](const EditorSession& current) {
        return resolve_condition(current.document, current.document.splits[0]->rules[0].rule.condition.value);
    };
    EXPECT_EQ(scalar_setting(require_condition(resolved_rule(session), 1), "duration"), "2s");

    apply_editor_command(session, nlohmann::json{
        {"type", "set_setting"},
        {"path", nlohmann::json::array({"definitions", "course_finish", "conditions", 1})},
        {"key", "duration"},
        {"value", "3s"},
    });
    EXPECT_EQ(scalar_setting(require_condition(resolved_rule(session), 1), "duration"), "3s");

    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage"},
        {"path", nlohmann::json::array({"splits", 0, "rules", 0, "condition"})},
        {"mode", "inherits"},
        {"anchor", "course_finish"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_override"},
        {"path", nlohmann::json::array({"splits", 0, "rules", 0, "condition"})},
        {"condition_id", "finish"},
        {"setting_path", nlohmann::json::array({"duration"})},
        {"value", "9s"},
    });
    EXPECT_EQ(scalar_setting(require_condition(resolved_rule(session), 1), "duration"), "9s");

    apply_editor_command(session, nlohmann::json{
        {"type", "remove_override"},
        {"path", nlohmann::json::array({"splits", 0, "rules", 0, "condition"})},
        {"condition_id", "finish"},
        {"setting_path", nlohmann::json::array({"duration"})},
    });
    EXPECT_EQ(scalar_setting(require_condition(resolved_rule(session), 1), "duration"), "3s");

    apply_editor_command(session, nlohmann::json{
        {"type", "move_condition"},
        {"path", nlohmann::json::array({"definitions", "course_finish"})},
        {"from", 0},
        {"to", 1},
    });
    const auto reordered = resolve_condition(
        session.document, session.document.definitions.front().value
    );
    EXPECT_EQ(scalar_setting(require_condition(reordered, 0), "id"), "finish");

    const std::size_t undo_before = session.undo_stack.size();
    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_EQ(session.undo_stack.size(), undo_before - 1U);
    apply_editor_command(session, nlohmann::json{{"type", "redo"}});
    EXPECT_EQ(session.undo_stack.size(), undo_before);

    TemporaryDirectory directory;
    const auto path = directory.path() / "saved.yaml";
    save_editor_session(session, path);
    EXPECT_FALSE(session.dirty);

    const auto reopened = open_editor_session(path);
    ASSERT_EQ(reopened.document.definitions.size(), 1U);
    EXPECT_EQ(reopened.document.definitions.front().name, "course_finish");
    ASSERT_EQ(reopened.document.splits.size(), 1U);
    ASSERT_TRUE(reopened.document.splits[0]->rules[0].rule.condition.is_inheritance());
    const auto loaded = load_scenario(path);
    EXPECT_NE(loaded.scenario.start_condition, nullptr);
}

TEST(ScenarioEditor, JsonStateContainsSharedDefinitionsAndConditionUsages) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "set_definition"},
        {"name", "shared"},
        {"value", {{"type", "elapsed"}, {"duration", "1s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage"},
        {"path", nlohmann::json::array({"start_condition"})},
        {"mode", "reference"},
        {"anchor", "shared"},
    });

    const auto state = editor_state_json(session);
    ASSERT_TRUE(state["document"]["definitions"].is_array());
    EXPECT_EQ(state["document"]["definitions"][0]["name"], "shared");
    EXPECT_EQ(state["document"]["definitions"][0]["resolved"]["type"], "elapsed");
    EXPECT_EQ(state["document"]["start_condition"]["$alias"], "shared");
    EXPECT_EQ(state["document"]["start_condition_resolved"]["type"], "elapsed");
    EXPECT_TRUE(state["canUndo"].get<bool>());
}

TEST(ScenarioEditor, OptionalConditionsCanBeToggledAndUndone) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "set_optional_condition"},
        {"name", "reset_condition"},
        {"enabled", true},
        {"value", {{"type", "elapsed"}, {"duration", "4s"}}},
    });
    ASSERT_TRUE(session.document.reset_condition.has_value());
    EXPECT_EQ(
        scalar_setting(session.document.reset_condition->value, "duration"),
        "4s"
    );

    apply_editor_command(session, nlohmann::json{
        {"type", "set_optional_condition"},
        {"name", "reset_condition"},
        {"enabled", false},
    });
    EXPECT_FALSE(session.document.reset_condition.has_value());

    apply_editor_command(session, nlohmann::json{{"type", "undo"}});
    EXPECT_TRUE(session.document.reset_condition.has_value());
}

TEST(ScenarioEditor, DeletingASharedDefinitionMaterializesItsReferences) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "set_definition"},
        {"name", "shared"},
        {"value", {{"id", "shared"}, {"type", "elapsed"}, {"duration", "7s"}}},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage"},
        {"path", nlohmann::json::array({"start_condition"})},
        {"mode", "reference"},
        {"anchor", "shared"},
    });
    apply_editor_command(session, nlohmann::json{{"type", "add_split"}, {"index", 0}});
    apply_editor_command(session, nlohmann::json{{"type", "add_rule"}, {"split", 0}});
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage"},
        {"path", nlohmann::json::array({"splits", 0, "rules", 0, "condition"})},
        {"mode", "inherits"},
        {"anchor", "shared"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_override"},
        {"path", nlohmann::json::array({"splits", 0, "rules", 0, "condition"})},
        {"condition_id", "shared"},
        {"setting_path", nlohmann::json::array({"duration"})},
        {"value", "8s"},
    });

    apply_editor_command(session, nlohmann::json{
        {"type", "delete_definition"},
        {"name", "shared"},
    });
    EXPECT_TRUE(session.document.definitions.empty());
    ASSERT_TRUE(session.document.start_condition.has_value());
    EXPECT_FALSE(session.document.start_condition->is_reference());
    EXPECT_EQ(scalar_setting(session.document.start_condition->value, "duration"), "7s");
    ASSERT_EQ(session.document.splits.size(), 1U);
    const auto& rule_condition = session.document.splits[0]->rules[0].rule.condition.value;
    EXPECT_FALSE(rule_condition.is_alias());
    EXPECT_EQ(scalar_setting(rule_condition, "duration"), "8s");
}

TEST(ScenarioEditor, PreservesSharedDetectorAnchors) {
    const auto document = import_scenario_yaml(R"(
detector: &bright
  type: mean_brightness
start_condition:
  type: detected
  minimum_score: 0.5
  detector: *bright
splits: []
)");
    ASSERT_EQ(document.definitions.size(), 1U);
    EXPECT_EQ(document.definitions[0].name, "bright");
    EXPECT_EQ(document.definitions[0].kind, DefinitionKind::detector);
    ASSERT_TRUE(document.start_condition.has_value());
    const auto* detector = document.start_condition->value.find("detector");
    ASSERT_NE(detector, nullptr);
    EXPECT_TRUE(detector->is_alias());
    EXPECT_EQ(detector->scalar, "bright");

    const std::string yaml = export_scenario_yaml(document);
    EXPECT_NE(yaml.find("&bright"), std::string::npos) << yaml;
    EXPECT_NE(yaml.find("detector: *bright"), std::string::npos) << yaml;
    const auto reloaded = import_scenario_yaml(yaml);
    ASSERT_EQ(reloaded.definitions.size(), 1U);
    EXPECT_EQ(reloaded.definitions[0].kind, DefinitionKind::detector);
}

TEST(ScenarioEditor, ConvertsAnAnchorDefiningUsageIntoAReference) {
    auto document = import_scenario_yaml(R"(
start_condition: &shared
  type: elapsed
  duration: 1s
splits:
  - rules:
      - condition: *shared
        action: split
)");
    ASSERT_EQ(document.definitions.size(), 1U);
    EXPECT_EQ(document.definitions[0].name, "shared");
    ASSERT_TRUE(document.start_condition.has_value());
    EXPECT_TRUE(document.start_condition->is_reference());
    EXPECT_EQ(document.start_condition->anchor(), "shared");
    const auto rule_condition = document.splits[0]->rules[0].rule.condition.value;
    EXPECT_TRUE(rule_condition.is_alias());

    document.definitions[0].value.set("duration", Value::make_scalar("4s"));
    EXPECT_EQ(scalar_setting(
        resolve_condition(document, document.start_condition->value), "duration"
    ), "4s");
    EXPECT_EQ(scalar_setting(resolve_condition(document, rule_condition), "duration"), "4s");

    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    save_scenario_document(document, path);
    const auto loaded = load_scenario(path);
    const auto* start = dynamic_cast<const ElapsedCondition*>(loaded.scenario.start_condition.get());
    ASSERT_NE(start, nullptr);
    EXPECT_EQ(start->duration(), std::chrono::seconds{4});
    ASSERT_EQ(loaded.scenario.splits.size(), 1U);
    const auto* split = dynamic_cast<const ElapsedCondition*>(
        loaded.scenario.splits[0]->at(0)->active_condition()
    );
    ASSERT_NE(split, nullptr);
    EXPECT_EQ(split->duration(), std::chrono::seconds{4});
}

TEST(ScenarioEditor, OrdersNestedAnchorDefinitionsBeforeTheirParents) {
    const auto document = import_scenario_yaml(R"(
definitions:
  first: &first
    type: detected
    minimum_score: 0.9
    detector: &shared_detector
      type: mean_brightness
  second: &second
    type: detected
    minimum_score: 0.8
    detector: *shared_detector
start_condition: *second
splits: []
)");
    ASSERT_EQ(document.definitions.size(), 3U);
    const auto* first = find_definition(document, "first");
    ASSERT_NE(first, nullptr);
    const auto* nested = first->value.find("detector");
    ASSERT_NE(nested, nullptr);
    EXPECT_TRUE(nested->is_alias());
    EXPECT_EQ(nested->scalar, "shared_detector");

    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    save_scenario_document(document, path);
    const auto yaml = read_text(path);
    const auto detector_position = yaml.find("&shared_detector");
    const auto first_position = yaml.find("&first");
    const auto second_position = yaml.find("&second");
    ASSERT_NE(detector_position, std::string::npos) << yaml;
    ASSERT_NE(first_position, std::string::npos) << yaml;
    ASSERT_NE(second_position, std::string::npos) << yaml;
    EXPECT_LT(detector_position, first_position) << yaml;
    EXPECT_LT(detector_position, second_position) << yaml;

    const auto loaded = load_scenario(path);
    const auto* start = dynamic_cast<const DetectedCondition*>(
        loaded.scenario.start_condition.get()
    );
    ASSERT_NE(start, nullptr);
    ASSERT_NE(start->detector(), nullptr);
    EXPECT_EQ(start->detector()->type_name(), "mean_brightness");
}

TEST(ScenarioEditor, RejectsUnsupportedOrAmbiguousAnchors) {
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
scalar_anchor: &scalar 1
start_condition: {type: elapsed, duration: 1s}
splits: []
)"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
sequence_anchor: &sequence [1, 2]
start_condition: {type: elapsed, duration: 1s}
splits: []
)"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
definitions:
  one: &same {type: elapsed, duration: 1s}
  two: &same {type: elapsed, duration: 2s}
start_condition: *same
splits: []
)"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
splits:
  - &split
    rules: []
start_condition: {type: elapsed, duration: 1s}
)"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
start_condition: *missing
splits: []
)"),
        ScenarioEditorError
    );
}

TEST(ScenarioEditor, RejectsInvalidInheritanceWithLoaderRules) {
    const std::string definitions = R"(
definitions:
  base: &base
    type: all
    conditions:
      - id: step
        type: elapsed
        duration: 1s
)";
    EXPECT_THROW(
        (void)import_scenario_yaml(definitions + R"(
start_condition:
  extends: *base
  overrides:
    missing:
      duration: 2s
splits: []
)"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(definitions + R"(
start_condition:
  extends: *base
  overrides:
    step:
      type: elapsed
splits: []
)"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(definitions + R"(
start_condition:
  extends: *base
  duration: 2s
splits: []
)"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
definitions:
  duplicate: &duplicate
    type: all
    conditions:
      - id: same
        type: elapsed
        duration: 1s
      - id: same
        type: elapsed
        duration: 2s
start_condition:
  extends: *duplicate
  overrides: {}
splits: []
)"),
        ScenarioEditorError
    );
}

TEST(ScenarioEditor, AppliesTheUsageIdWhenResolvingExtends) {
    const auto document = import_scenario_yaml(R"(
definitions:
  base: &base
    id: inherited
    type: elapsed
    duration: 1s
start_condition:
  extends: *base
  id: local
  overrides: {}
splits: []
)");
    ASSERT_TRUE(document.start_condition.has_value());
    const auto resolved = resolve_condition(document, document.start_condition->value);
    EXPECT_EQ(scalar_setting(resolved, "id"), "local");
}

TEST(ScenarioEditor, SaveRejectsInvalidYamlAndKeepsTheOriginalFile) {
    TemporaryDirectory directory;
    const auto path = directory.path() / "scenario.yaml";
    const std::string original = R"(
start_condition: {type: elapsed, duration: 1s}
splits: []
)";
    write_text(path, original);

    auto document = import_scenario_yaml(original);
    document.start_condition->value.set("type", Value::make_scalar("unsupported"));
    EXPECT_THROW(save_scenario_document(document, path), ScenarioEditorError);
    EXPECT_EQ(read_text(path), original);
    EXPECT_EQ(std::distance(
        std::filesystem::directory_iterator{directory.path()},
        std::filesystem::directory_iterator{}
    ), 1);
}

TEST(ScenarioEditor, RejectsOverrideCommandsWithUnknownConditionIds) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "set_definition"},
        {"name", "base"},
        {"value", {
            {"type", "all"},
            {"conditions", nlohmann::json::array({
                {{"id", "step"}, {"type", "elapsed"}, {"duration", "1s"}},
            })},
        }},
    });
    apply_editor_command(session, nlohmann::json{{"type", "add_split"}, {"index", 0}});
    apply_editor_command(session, nlohmann::json{{"type", "add_rule"}, {"split", 0}});
    apply_editor_command(session, nlohmann::json{
        {"type", "set_usage"},
        {"path", nlohmann::json::array({"splits", 0, "rules", 0, "condition"})},
        {"mode", "inherits"},
        {"anchor", "base"},
    });
    const std::size_t undo_before = session.undo_stack.size();
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "set_override"},
            {"path", nlohmann::json::array({"splits", 0, "rules", 0, "condition"})},
            {"condition_id", "missing"},
            {"setting_path", nlohmann::json::array({"duration"})},
            {"value", "2s"},
        }),
        ScenarioEditorError
    );
    EXPECT_EQ(session.undo_stack.size(), undo_before);
    EXPECT_EQ(
        session.document.splits[0]->rules[0].rule.condition.value.find("overrides"),
        nullptr
    );
}

TEST(ScenarioEditor, RejectsUnknownAndMissingConditionFields) {
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
start_condition: {type: elapsed, duration: 1s, extra: value}
splits: []
)"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
start_condition: {type: elapsed}
splits: []
)"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
start_condition:
  type: detected
  minimum_score: 0.5
  detector:
    type: mean_brightness
    reference: reference.png
splits: []
)"),
        ScenarioEditorError
    );
    EXPECT_THROW(
        (void)import_scenario_yaml(R"(
start_condition:
  type: detected
  minimum_score: 0.5
  detector:
    type: template_match
    reference: reference.png
    unknown: value
splits: []
)"),
        ScenarioEditorError
    );
}

TEST(ScenarioEditor, CommandsRejectUnknownOrMissingFields) {
    EditorSession session = new_editor_session();
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "set_setting"},
            {"path", nlohmann::json::array({"start_condition"})},
            {"key", "unknown"},
            {"value", "1"},
        }),
        ScenarioEditorError
    );
    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "remove_setting"},
            {"path", nlohmann::json::array({"start_condition"})},
            {"key", "duration"},
        }),
        ScenarioEditorError
    );
    EXPECT_TRUE(session.undo_stack.empty());
}

TEST(ScenarioEditor, ChangingTypesUsesTheFixedFieldSchema) {
    EditorSession session = new_editor_session();
    apply_editor_command(session, nlohmann::json{
        {"type", "set_setting"},
        {"path", nlohmann::json::array({"start_condition"})},
        {"key", "id"},
        {"value", "root"},
    });
    apply_editor_command(session, nlohmann::json{
        {"type", "set_condition_type"},
        {"path", nlohmann::json::array({"start_condition"})},
        {"value", "all"},
    });
    const auto& start = session.document.start_condition->value;
    EXPECT_EQ(scalar_setting(start, "type"), "all");
    EXPECT_EQ(scalar_setting(start, "id"), "root");
    EXPECT_NE(start.find("conditions"), nullptr);
    EXPECT_EQ(start.find("duration"), nullptr);

    apply_editor_command(session, nlohmann::json{
        {"type", "set_condition_type"},
        {"path", nlohmann::json::array({"start_condition"})},
        {"value", "detected"},
    });
    const auto& detected = session.document.start_condition->value;
    ASSERT_NE(detected.find("detector"), nullptr);
    EXPECT_EQ(scalar_setting(*detected.find("detector"), "type"), "mean_brightness");

    apply_editor_command(session, nlohmann::json{
        {"type", "set_detector_type"},
        {"path", nlohmann::json::array({"start_condition", "detector"})},
        {"value", "template_match"},
    });
    const auto& detector = *session.document.start_condition->value.find("detector");
    EXPECT_EQ(scalar_setting(detector, "type"), "template_match");
    EXPECT_EQ(scalar_setting(detector, "reference"), "reference.png");
    EXPECT_EQ(detector.find("roi"), nullptr);

    EXPECT_THROW(
        apply_editor_command(session, nlohmann::json{
            {"type", "set_setting"},
            {"path", nlohmann::json::array({"start_condition", "detector"})},
            {"key", "unknown"},
            {"value", "1"},
        }),
        ScenarioEditorError
    );
}

TEST(ScenarioEditor, JsonStateExposesTheFixedFieldSchema) {
    EditorSession session = new_editor_session();
    const auto state = editor_state_json(session);
    ASSERT_TRUE(state["schema"]["conditionFields"].contains("elapsed"));
    ASSERT_TRUE(state["schema"]["conditionFields"].contains("detected"));
    ASSERT_TRUE(state["schema"]["detectorFields"].contains("mean_brightness"));
    const auto& elapsed = state["schema"]["conditionFields"]["elapsed"];
    ASSERT_EQ(elapsed.size(), 1U);
    EXPECT_EQ(elapsed[0]["name"], "duration");
    EXPECT_EQ(elapsed[0]["kind"], "duration");
    EXPECT_TRUE(elapsed[0]["required"].get<bool>());
    EXPECT_EQ(elapsed[0]["default"], "1s");
}
