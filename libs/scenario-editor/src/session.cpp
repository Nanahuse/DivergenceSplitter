#include "divergencesplitter/scenario/editor/document.hpp"

#include <cstddef>
#include <optional>
#include <system_error>
#include <utility>

#include "divergencesplitter/scenario/editor/workspace.hpp"
#include "editor_detail.hpp"

namespace divergencesplitter::scenario_editor {
namespace {

constexpr std::size_t max_undo_steps = 256;

void validate_asset_references(
    const ScenarioDocument& document,
    const ScenarioWorkspace& workspace
) {
    const auto scan = [&](const auto& self, const Value& value) -> void {
        if (value.is_mapping()) {
            for (const auto& [key, item] : value.mapping) {
                if (key == "reference" && item.is_scalar()) {
                    try {
                        const auto path = workspace.resolve_asset_reference(item.scalar);
                        std::error_code error;
                        if (!std::filesystem::is_regular_file(path, error) || error) {
                            throw ScenarioEditorError(
                                "referenced image was not found: " + item.scalar
                            );
                        }
                    } catch (const ScenarioEditorError& error) {
                        throw ScenarioEditorError(
                            "invalid image reference '" + item.scalar + "': " + error.what()
                        );
                    }
                } else {
                    self(self, item);
                }
            }
            return;
        }
        if (value.is_sequence()) {
            for (const auto& item : value.sequence) {
                self(self, item);
            }
        }
    };

    for (const auto& definition : document.definitions.conditions) {
        scan(
            scan,
            scenario::v2::resolve_condition(
                document.definitions,
                Value::make_mapping({{"use", Value::make_scalar(definition.name)}})
            )
        );
    }
    for (const auto& definition : document.definitions.detectors) {
        scan(
            scan,
            scenario::v2::resolve_detector(
                document.definitions,
                Value::make_mapping({{"use", Value::make_scalar(definition.name)}})
            )
        );
    }
    const auto scan_usage = [&](const std::optional<ConditionUsage>& usage) {
        if (usage) {
            scan(scan, resolved_condition(document, usage->value));
        }
    };
    scan_usage(document.start_condition);
    scan_usage(document.reset_condition);
    scan_usage(document.incomplete_condition);
    for (const auto& split : document.splits) {
        if (!split) {
            continue;
        }
        for (const auto& rule : split->rules) {
            if (rule.sequence) {
                for (const auto& step : rule.sequence_rules) {
                    scan(scan, resolved_condition(document, step.condition.value));
                }
            } else {
                scan(scan, resolved_condition(document, rule.rule.condition.value));
            }
        }
    }
}

}  // namespace

EditorSession new_editor_session(std::filesystem::path workspace_root) {
    EditorSession session;
    session.workspace_root = std::move(workspace_root);
    session.document.start_condition = ConditionUsage{
        Value::make_mapping({
            {"type", Value::make_scalar("elapsed")},
            {"duration", Value::make_scalar("2s")},
        })
    };
    return session;
}

EditorSession open_editor_session(
    const std::filesystem::path& path,
    std::filesystem::path workspace_root
) {
    EditorSession session;
    session.document = load_scenario_document(path);
    session.path = path;
    session.workspace_root = std::move(workspace_root);
    return session;
}

void apply_editor_command(EditorSession& session, const nlohmann::json& command) {
    if (!command.is_object() || !command.contains("type") || !command["type"].is_string()) {
        throw ScenarioEditorError("editor command must have a type");
    }
    const std::string type = command["type"].get<std::string>();
    if (type == "undo") {
        undo_editor(session);
        return;
    }
    if (type == "redo") {
        redo_editor(session);
        return;
    }
    ScenarioDocument next = session.document;
    detail::mutate_document(next, command);
    validate_scenario_document(next);
    if (session.undo_stack.size() >= max_undo_steps) {
        session.undo_stack.erase(session.undo_stack.begin());
    }
    session.undo_stack.push_back(std::move(session.document));
    session.document = std::move(next);
    session.redo_stack.clear();
    session.dirty = true;
}

void undo_editor(EditorSession& session) {
    if (session.undo_stack.empty()) {
        throw ScenarioEditorError("nothing to undo");
    }
    session.redo_stack.push_back(std::move(session.document));
    session.document = std::move(session.undo_stack.back());
    session.undo_stack.pop_back();
    session.dirty = true;
}

void redo_editor(EditorSession& session) {
    if (session.redo_stack.empty()) {
        throw ScenarioEditorError("nothing to redo");
    }
    session.undo_stack.push_back(std::move(session.document));
    session.document = std::move(session.redo_stack.back());
    session.redo_stack.pop_back();
    session.dirty = true;
}

void save_editor_session(EditorSession& session, const std::filesystem::path& path) {
    if (!session.workspace_root.empty()) {
        ScenarioWorkspace workspace;
        workspace.open(session.workspace_root);
        workspace.validate_scenario_destination(path);
        validate_asset_references(session.document, workspace);
    }
    save_scenario_document(session.document, path);
    session.path = path;
    session.dirty = false;
}

}  // namespace divergencesplitter::scenario_editor
