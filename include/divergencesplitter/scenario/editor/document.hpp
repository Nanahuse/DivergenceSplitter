#pragma once

#include <filesystem>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include <nlohmann/json.hpp>

#include "divergencesplitter/scenario/editor/model.hpp"

namespace divergencesplitter::scenario_editor {

// The importer deliberately reads anchors and aliases without calling
// ryml::Tree::resolve(), so shared definitions remain references in the model.
[[nodiscard]] ScenarioDocument import_scenario_yaml(
    std::string_view source,
    std::string source_name = "<memory>"
);
[[nodiscard]] ScenarioDocument load_scenario_document(const std::filesystem::path& path);

[[nodiscard]] std::string export_scenario_yaml(const ScenarioDocument& document);
void save_scenario_document(const ScenarioDocument& document, const std::filesystem::path& path);

[[nodiscard]] nlohmann::json value_to_json(const Value& value);
[[nodiscard]] Value value_from_json(const nlohmann::json& value);

struct EditorSession {
    ScenarioDocument document;
    std::filesystem::path path;
    bool dirty{false};
    std::vector<ScenarioDocument> undo_stack;
    std::vector<ScenarioDocument> redo_stack;
};

[[nodiscard]] EditorSession new_editor_session();
[[nodiscard]] EditorSession open_editor_session(const std::filesystem::path& path);

// Mutating commands take a snapshot of the document before applying the edit.
// A failed command leaves both the document and the history untouched.
void apply_editor_command(EditorSession& session, const nlohmann::json& command);
void undo_editor(EditorSession& session);
void redo_editor(EditorSession& session);
void save_editor_session(EditorSession& session, const std::filesystem::path& path);

[[nodiscard]] nlohmann::json editor_state_json(const EditorSession& session);
[[nodiscard]] std::string path_to_utf8(const std::filesystem::path& path);
[[nodiscard]] std::filesystem::path path_from_utf8(std::string_view path);

}  // namespace divergencesplitter::scenario_editor
