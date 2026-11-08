# ---------------------------------------------------------------------------
# Core: frame data, detectors, conditions, rules, and scenarios.
# ---------------------------------------------------------------------------

add_library(divergencesplitter_core STATIC
    core/frame_normalizer.cpp
    core/detectors.cpp
    core/conditions.cpp
    core/rules.cpp
    core/scenario_loader.cpp
    core/text.cpp
)

add_library(divergencesplitter::core ALIAS divergencesplitter_core)

target_compile_features(divergencesplitter_core PUBLIC cxx_std_23)
target_include_directories(divergencesplitter_core
    PUBLIC
        $<BUILD_INTERFACE:${PROJECT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)
target_link_libraries(divergencesplitter_core
    PUBLIC
        opencv_core
        opencv_imgproc
        opencv_imgcodecs
        opencv_videoio
        ryml::ryml
        nlohmann_json::nlohmann_json
        Threads::Threads
)

# ---------------------------------------------------------------------------
# Runtime: LiveSplit mapping, instance threads, capture, configuration.
# ---------------------------------------------------------------------------

add_library(divergencesplitter_runtime STATIC
    runtime/evaluation_history.cpp
    runtime/scenario_runtime.cpp
    runtime/instance_runtime.cpp
    runtime/livesplit_adapter.cpp
    runtime/livesplit_client.cpp
    runtime/session.cpp
    runtime/configuration.cpp
    runtime/logging.cpp
    capture/frame_sources.cpp
    capture/configured_source.cpp
    capture/camera_devices.cpp
    capture/capture_pipeline.cpp
    capture/ndi.cpp
    capture/ndi_sdk.cpp
)

add_library(divergencesplitter::runtime ALIAS divergencesplitter_runtime)

target_compile_features(divergencesplitter_runtime PUBLIC cxx_std_23)
target_include_directories(divergencesplitter_runtime SYSTEM PRIVATE
    "${PROJECT_SOURCE_DIR}/third_party/ndi/include")
target_link_libraries(divergencesplitter_runtime
    PUBLIC
        divergencesplitter::core
    PRIVATE
        livesplit_bridge::livesplit_bridge
)

if(WIN32)
    target_compile_definitions(divergencesplitter_runtime PRIVATE _WIN32_WINNT=0x0A00 WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(divergencesplitter_runtime PRIVATE
        ws2_32 mswsock
        ole32 oleaut32 strmiids mf mfplat mfuuid mfreadwrite
    )
endif()


# ---------------------------------------------------------------------------
# Dear ImGui UI (Win32 window, Direct3D 11 renderer).
# ---------------------------------------------------------------------------

if(DIVERGENCESPLITTER_BUILD_UI)
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
        ui/about_page.hpp
        ui/app.hpp
        ui/app_controller.hpp
        ui/file_dialog.hpp
        ui/image_texture.hpp
        ui/license_inventory.hpp
        ui/monitor_model.hpp
        ui/monitor_page.hpp
        ui/ndi_discovery.hpp
        ui/profile_document.hpp
        ui/profile_page.hpp
        ui/profile_preview.hpp
        ui/profile_source_ui.hpp
        ui/settings_page.hpp
        ui/theme.hpp
        ui/ui_helpers.hpp
        ui/about_page.cpp
        ui/app.cpp
        ui/app_controller.cpp
        ui/file_dialog.cpp
        ui/image_texture.cpp
        ui/license_inventory.cpp
        ui/history_plot.cpp
        ui/monitor_model.cpp
        ui/monitor_page.cpp
        ui/ndi_discovery.cpp
        ui/profile_page.cpp
        ui/profile_preview.cpp
        ui/profile_source_ui.cpp
        ui/settings_page.cpp
        ui/theme.cpp
        ui/ui_helpers.cpp
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
    # UI headers are internal; only the application and UI tests need this path.
    target_include_directories(divergencesplitter_ui PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/ui")

    add_executable(DivergenceSplitter WIN32 ui/main.cpp)
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
endif()
