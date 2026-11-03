# ---------------------------------------------------------------------------
# Core: frame data, detectors, conditions, rules, and scenarios.
# ---------------------------------------------------------------------------

add_library(divergencesplitter_core STATIC
    core/frame_normalizer.cpp
    core/detectors.cpp
    core/conditions.cpp
    core/rules.cpp
    core/scenario_loader.cpp
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
target_compile_definitions(divergencesplitter_runtime PUBLIC
    DIVERGENCESPLITTER_ENABLE_NDI=$<BOOL:${DIVERGENCESPLITTER_ENABLE_NDI}>)
if(DIVERGENCESPLITTER_ENABLE_NDI)
    target_include_directories(divergencesplitter_runtime SYSTEM PRIVATE "${NDI_SDK_DIR}/Include")
    # Dynamic-load function table only; no NDI import library is linked.
    configure_file("${NDI_RUNTIME_DLL}" "${CMAKE_BINARY_DIR}/Processing.NDI.Lib.x64.dll" COPYONLY)
endif()
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
# CLI (headless runner used by CI and verification).
# ---------------------------------------------------------------------------

add_executable(divergencesplitter_cli cli/main.cpp)
target_compile_features(divergencesplitter_cli PRIVATE cxx_std_23)
target_link_libraries(divergencesplitter_cli PRIVATE divergencesplitter::runtime)
set_target_properties(divergencesplitter_cli PROPERTIES OUTPUT_NAME divergencesplitter-cli)

# ---------------------------------------------------------------------------
# Qt Widgets UI.
# ---------------------------------------------------------------------------

if(DIVERGENCESPLITTER_BUILD_UI)
    qt_standard_project_setup()

    add_library(divergencesplitter_ui STATIC
        ui/about_page.hpp
        ui/app_controller.hpp
        ui/diagnostics_page.hpp
        ui/image_view.hpp
        ui/main_window.hpp
        ui/monitor_page.hpp
        ui/profile_page.hpp
        ui/profile_preview.hpp
        ui/reset_all_button.hpp
        ui/settings_page.hpp
        ui/app_controller.cpp
        ui/main_window.cpp
        ui/monitor_page.cpp
        ui/diagnostics_page.cpp
        ui/profile_page.cpp
        ui/profile_preview.cpp
        ui/settings_page.cpp
        ui/about_page.cpp
        ui/reset_all_button.cpp
        ui/image_view.cpp
    )
    add_library(divergencesplitter::ui ALIAS divergencesplitter_ui)

    target_compile_features(divergencesplitter_ui PUBLIC cxx_std_23)
    target_compile_definitions(divergencesplitter_ui
        PUBLIC DIVERGENCESPLITTER_VERSION="${PROJECT_VERSION}"
    )
    target_link_libraries(divergencesplitter_ui
        PUBLIC
            divergencesplitter::runtime
            Qt6::Widgets
    )
    # UI headers are internal; only the application and UI tests need this path.
    target_include_directories(divergencesplitter_ui PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/ui")
    set_target_properties(divergencesplitter_ui PROPERTIES AUTOMOC ON)

    add_executable(DivergenceSplitter WIN32 ui/main.cpp)
    target_link_libraries(DivergenceSplitter PRIVATE divergencesplitter::ui)

    set_target_properties(DivergenceSplitter PROPERTIES
        WIN32_EXECUTABLE TRUE
        OUTPUT_NAME "DivergenceSplitter"
    )

    if(WIN32)
        if(CMAKE_BUILD_TYPE STREQUAL "Debug")
            add_custom_command(
                TARGET DivergenceSplitter POST_BUILD
                COMMAND "${CMAKE_COMMAND}" -E copy_directory
                    "${VCPKG_INSTALLED_DIR}/x64-windows/debug/Qt6/plugins"
                    "$<TARGET_FILE_DIR:DivergenceSplitter>"
                COMMENT "Copying Qt debug plugins next to DivergenceSplitter"
            )
        else()
            get_target_property(_qmake Qt6::qmake IMPORTED_LOCATION)
            get_filename_component(_qt_bin "${_qmake}" DIRECTORY)
            find_program(WINDEPLOYQT_EXECUTABLE windeployqt HINTS "${_qt_bin}")
            if(WINDEPLOYQT_EXECUTABLE)
                add_custom_command(
                    TARGET DivergenceSplitter POST_BUILD
                    COMMAND "${WINDEPLOYQT_EXECUTABLE}"
                        --no-translations
                        --no-system-d3d-compiler
                        --no-opengl-sw
                        "$<TARGET_FILE:DivergenceSplitter>"
                    COMMENT "Deploying Qt release runtime next to DivergenceSplitter"
                )
            endif()
        endif()
    endif()
endif()
