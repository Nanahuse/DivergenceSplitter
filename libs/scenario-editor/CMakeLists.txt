add_library(divergencesplitter_scenario_editor STATIC
    src/commands.cpp
    src/editor_detail.cpp
    src/editor_state.cpp
    src/model.cpp
    src/schema.cpp
    src/session.cpp
    src/value_json.cpp
    src/workspace.cpp
    src/yaml_export.cpp
    src/yaml_import.cpp
)

add_library(divergencesplitter::scenario_editor ALIAS divergencesplitter_scenario_editor)

target_compile_features(divergencesplitter_scenario_editor PUBLIC cxx_std_23)
target_include_directories(divergencesplitter_scenario_editor
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)
target_link_libraries(divergencesplitter_scenario_editor
    PUBLIC
        divergencesplitter::core
        nlohmann_json::nlohmann_json
)
