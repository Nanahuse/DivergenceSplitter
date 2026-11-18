add_library(divergencesplitter_imgui STATIC
    "${imgui_SOURCE_DIR}/imgui.cpp"
    "${imgui_SOURCE_DIR}/imgui_draw.cpp"
    "${imgui_SOURCE_DIR}/imgui_tables.cpp"
    "${imgui_SOURCE_DIR}/imgui_widgets.cpp"
    "${imgui_SOURCE_DIR}/backends/imgui_impl_win32.cpp"
    "${imgui_SOURCE_DIR}/backends/imgui_impl_dx11.cpp"
)
target_include_directories(divergencesplitter_imgui SYSTEM PUBLIC
    "${imgui_SOURCE_DIR}"
    "${imgui_SOURCE_DIR}/backends"
)
target_link_libraries(divergencesplitter_imgui PUBLIC d3d11 dxgi)

add_library(divergencesplitter_implot STATIC
    "${implot_SOURCE_DIR}/implot.cpp"
    "${implot_SOURCE_DIR}/implot_items.cpp"
)
target_include_directories(divergencesplitter_implot SYSTEM PUBLIC "${implot_SOURCE_DIR}")
target_link_libraries(divergencesplitter_implot PUBLIC divergencesplitter_imgui)

add_library(divergencesplitter_ui STATIC
    src/ui/about_page.hpp
    src/ui/app.hpp
    src/ui/app_controller.hpp
    src/ui/file_dialog.hpp
    src/ui/history_plot.hpp
    src/ui/image_texture.hpp
    src/ui/license_inventory.hpp
    src/ui/monitor_model.hpp
    src/ui/monitor_page.hpp
    src/ui/monitor_row.hpp
    src/ui/ndi_discovery.hpp
    src/ui/profile_document.hpp
    src/ui/profile_page.hpp
    src/ui/profile_preview.hpp
    src/ui/profile_source_ui.hpp
    src/ui/settings_page.hpp
    src/ui/theme.hpp
    src/ui/ui_helpers.hpp
    src/ui/about_page.cpp
    src/ui/app.cpp
    src/ui/app_controller.cpp
    src/ui/file_dialog.cpp
    src/ui/image_texture.cpp
    src/ui/license_inventory.cpp
    src/ui/history_plot.cpp
    src/ui/monitor_model.cpp
    src/ui/monitor_page.cpp
    src/ui/monitor_row.cpp
    src/ui/ndi_discovery.cpp
    src/ui/profile_page.cpp
    src/ui/profile_preview.cpp
    src/ui/profile_source_ui.cpp
    src/ui/settings_page.cpp
    src/ui/theme.cpp
    src/ui/ui_helpers.cpp
)
add_library(divergencesplitter::ui ALIAS divergencesplitter_ui)

target_compile_features(divergencesplitter_ui PUBLIC cxx_std_23)
target_compile_definitions(divergencesplitter_ui
    PUBLIC DIVERGENCESPLITTER_VERSION="${PROJECT_VERSION}"
    PRIVATE _WIN32_WINNT=0x0A00 WIN32_LEAN_AND_MEAN NOMINMAX
)
target_link_libraries(divergencesplitter_ui
    PUBLIC
        divergencesplitter::runtime
    PRIVATE
        divergencesplitter_imgui
        divergencesplitter_implot
        d3d11 dxgi shell32 ole32 uuid
)
target_include_directories(divergencesplitter_ui PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/resources")

if(DIVERGENCESPLITTER_BUILD_BENCHMARKS)
    add_executable(monitor_history_benchmark "${PROJECT_SOURCE_DIR}/tools/monitor_history_benchmark.cpp")
    target_link_libraries(monitor_history_benchmark PRIVATE divergencesplitter::ui divergencesplitter_implot)
    target_include_directories(monitor_history_benchmark PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/src/ui")
endif()

add_executable(DivergenceSplitter WIN32 src/main.cpp resources/app.rc)
target_include_directories(DivergenceSplitter PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}/src/ui"
    "${CMAKE_CURRENT_SOURCE_DIR}/resources"
)
set_source_files_properties(resources/app.rc PROPERTIES
    OBJECT_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/resources/icon.ico"
)
target_link_libraries(DivergenceSplitter PRIVATE divergencesplitter::ui divergencesplitter_imgui)
target_compile_definitions(DivergenceSplitter PRIVATE _WIN32_WINNT=0x0A00 WIN32_LEAN_AND_MEAN NOMINMAX)

set_target_properties(DivergenceSplitter PROPERTIES
    WIN32_EXECUTABLE TRUE
    OUTPUT_NAME "DivergenceSplitter"
)
add_custom_command(
    TARGET DivergenceSplitter POST_BUILD
    COMMAND "${CMAKE_COMMAND}" -E copy_directory
        "${PROJECT_SOURCE_DIR}/licenses"
        "$<TARGET_FILE_DIR:DivergenceSplitter>/licenses"
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        "${PROJECT_SOURCE_DIR}/LICENSE"
        "$<TARGET_FILE_DIR:DivergenceSplitter>/LICENSE.txt"
    COMMAND "${CMAKE_COMMAND}" -E copy_if_different
        "${PROJECT_SOURCE_DIR}/DISTRIBUTION-NOTICE.txt"
        "$<TARGET_FILE_DIR:DivergenceSplitter>/DISTRIBUTION-NOTICE.txt"
    COMMENT "Copying license inventory next to DivergenceSplitter"
)
