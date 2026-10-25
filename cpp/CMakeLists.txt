cmake_minimum_required(VERSION 3.25)

project(
    DivergenceSplitter
    VERSION 0.1.0
    DESCRIPTION "Automatic splitter for LiveSplit.Bridge"
    HOMEPAGE_URL "https://github.com/Nanahuse/DivergenceSplitter"
    LANGUAGES CXX
)

option(DIVERGENCESPLITTER_BUILD_UI "Build the Qt Widgets desktop UI" ON)
option(DIVERGENCESPLITTER_BUILD_TESTS "Build the CTest suite" ON)
option(DIVERGENCESPLITTER_BUILD_TESTHOST_TESTS "Build the optional LiveSplit.Bridge TestHost smoke test" OFF)
option(DIVERGENCESPLITTER_FETCH_BRIDGE "Fetch the LiveSplit Bridge C++ client" ON)

set(
    DIVERGENCESPLITTER_BRIDGE_TAG
    "v0.1.0"
    CACHE STRING
    "livesplit-bridge-client-cpp tag or commit to fetch"
)

if(MSVC)
    add_compile_options(/W4 /permissive- /Zc:__cplusplus /utf-8 /EHsc)
    add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
else()
    add_compile_options(-Wall -Wextra -Wpedantic)
endif()

include(FetchContent)
find_package(OpenCV CONFIG REQUIRED COMPONENTS core imgproc imgcodecs videoio)
find_package(yaml-cpp CONFIG REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)
find_package(Threads REQUIRED)

if(DIVERGENCESPLITTER_FETCH_BRIDGE)
    set(LIVESPLIT_BRIDGE_BUILD_CLI OFF CACHE BOOL "" FORCE)
    set(LIVESPLIT_BRIDGE_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    FetchContent_Declare(
        livesplit_bridge
        GIT_REPOSITORY https://github.com/Nanahuse/livesplit-bridge-client-cpp.git
        GIT_TAG ${DIVERGENCESPLITTER_BRIDGE_TAG}
        GIT_SHALLOW TRUE
    )
    FetchContent_MakeAvailable(livesplit_bridge)
endif()

if(NOT TARGET livesplit_bridge::livesplit_bridge)
    message(FATAL_ERROR "livesplit_bridge::livesplit_bridge is required")
endif()

# ---------------------------------------------------------------------------
# Core: frame data, detectors, conditions, rules, and scenarios.
# ---------------------------------------------------------------------------

add_library(divergencesplitter_core STATIC
    src/core/detectors.cpp
    src/core/conditions.cpp
    src/core/rules.cpp
    src/core/scenario_loader.cpp
)

add_library(divergencesplitter::core ALIAS divergencesplitter_core)

target_compile_features(divergencesplitter_core PUBLIC cxx_std_23)
target_include_directories(divergencesplitter_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)
target_link_libraries(divergencesplitter_core
    PUBLIC
        opencv_core
        opencv_imgproc
        opencv_imgcodecs
        opencv_videoio
        yaml-cpp::yaml-cpp
        nlohmann_json::nlohmann_json
        Threads::Threads
)

# ---------------------------------------------------------------------------
# Runtime: LiveSplit mapping, instance threads, capture, configuration.
# ---------------------------------------------------------------------------

add_library(divergencesplitter_runtime STATIC
    src/runtime/scenario_runtime.cpp
    src/runtime/instance_runtime.cpp
    src/runtime/livesplit_adapter.cpp
    src/runtime/livesplit_client.cpp
    src/runtime/session.cpp
    src/runtime/configuration.cpp
    src/runtime/logging.cpp
    src/capture/frame_sources.cpp
    src/capture/capture_pipeline.cpp
)

add_library(divergencesplitter::runtime ALIAS divergencesplitter_runtime)

target_compile_features(divergencesplitter_runtime PUBLIC cxx_std_23)
target_link_libraries(divergencesplitter_runtime
    PUBLIC
        divergencesplitter::core
    PRIVATE
        livesplit_bridge::livesplit_bridge
)

if(WIN32)
    target_compile_definitions(divergencesplitter_runtime PRIVATE _WIN32_WINNT=0x0A00 WIN32_LEAN_AND_MEAN NOMINMAX)
    target_link_libraries(divergencesplitter_runtime PRIVATE ws2_32 mswsock)
endif()


# ---------------------------------------------------------------------------
# CLI (headless runner used by CI and verification).
# ---------------------------------------------------------------------------

add_executable(divergencesplitter_cli src/cli/main.cpp)
target_compile_features(divergencesplitter_cli PRIVATE cxx_std_23)
target_link_libraries(divergencesplitter_cli PRIVATE divergencesplitter::runtime)
set_target_properties(divergencesplitter_cli PROPERTIES OUTPUT_NAME divergencesplitter-cli)

# ---------------------------------------------------------------------------
# Qt Widgets UI.
# ---------------------------------------------------------------------------

if(DIVERGENCESPLITTER_BUILD_UI)
    find_package(Qt6 REQUIRED COMPONENTS Widgets Test)
    qt_standard_project_setup()

    add_library(divergencesplitter_ui STATIC
        include/divergencesplitter/ui/about_page.hpp
        include/divergencesplitter/ui/app_controller.hpp
        include/divergencesplitter/ui/diagnostics_page.hpp
        include/divergencesplitter/ui/image_view.hpp
        include/divergencesplitter/ui/main_window.hpp
        include/divergencesplitter/ui/monitor_page.hpp
        include/divergencesplitter/ui/profile_page.hpp
        include/divergencesplitter/ui/reset_all_button.hpp
        include/divergencesplitter/ui/settings_page.hpp
        src/ui/app_controller.cpp
        src/ui/main_window.cpp
        src/ui/monitor_page.cpp
        src/ui/diagnostics_page.cpp
        src/ui/profile_page.cpp
        src/ui/settings_page.cpp
        src/ui/about_page.cpp
        src/ui/reset_all_button.cpp
        src/ui/image_view.cpp
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
    set_target_properties(divergencesplitter_ui PROPERTIES AUTOMOC ON)

    add_executable(DivergenceSplitter WIN32 src/ui/main.cpp)
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

# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------

if(DIVERGENCESPLITTER_BUILD_TESTS)
    enable_testing()
    find_package(GTest CONFIG REQUIRED)
    include(GoogleTest)

    add_executable(divergencesplitter_tests
        tests/condition_tests.cpp
        tests/detector_tests.cpp
        tests/frame_cache_tests.cpp
        tests/instance_runtime_tests.cpp
        tests/logging_tests.cpp
        tests/normalizer_tests.cpp
        tests/profile_tests.cpp
        tests/scenario_loader_tests.cpp
        tests/scenario_runtime_tests.cpp
        tests/test_support.cpp
    )
    target_compile_features(divergencesplitter_tests PRIVATE cxx_std_23)
    target_link_libraries(divergencesplitter_tests
        PRIVATE
            divergencesplitter::runtime
            GTest::gtest_main
    )
    target_include_directories(divergencesplitter_tests PRIVATE tests)
    gtest_discover_tests(divergencesplitter_tests)

    if(DIVERGENCESPLITTER_BUILD_TESTHOST_TESTS)
        add_executable(divergencesplitter_testhost_tests tests/testhost_tests.cpp)
        target_compile_features(divergencesplitter_testhost_tests PRIVATE cxx_std_23)
        target_link_libraries(divergencesplitter_testhost_tests
            PRIVATE
                divergencesplitter::runtime
                GTest::gtest_main
        )
        add_test(NAME divergencesplitter_testhost_tests COMMAND divergencesplitter_testhost_tests)
    endif()

    if(DIVERGENCESPLITTER_BUILD_UI)
        add_executable(divergencesplitter_ui_tests tests/ui_tests.cpp)
        target_compile_features(divergencesplitter_ui_tests PRIVATE cxx_std_23)
        target_link_libraries(divergencesplitter_ui_tests
            PRIVATE
                divergencesplitter::ui
                Qt6::Test
        )
        set_target_properties(divergencesplitter_ui_tests PROPERTIES AUTOMOC ON)
        add_test(NAME divergencesplitter_ui_tests COMMAND divergencesplitter_ui_tests)
        if(CMAKE_BUILD_TYPE STREQUAL "Debug")
            set(_qt_test_plugin_path "${VCPKG_INSTALLED_DIR}/x64-windows/debug/Qt6/plugins")
        else()
            set(_qt_test_plugin_path "${VCPKG_INSTALLED_DIR}/x64-windows/Qt6/plugins")
        endif()
        set(_ui_test_environment "QT_QPA_PLATFORM=offscreen")
        if(EXISTS "${_qt_test_plugin_path}")
            string(APPEND _ui_test_environment ";QT_PLUGIN_PATH=${_qt_test_plugin_path}")
        endif()
        set_tests_properties(divergencesplitter_ui_tests PROPERTIES
            ENVIRONMENT "${_ui_test_environment}"
            TIMEOUT 120
        )
    endif()
endif()

# ---------------------------------------------------------------------------
# Install / ZIP distribution.
# ---------------------------------------------------------------------------

include(GNUInstallDirs)

if(TARGET DivergenceSplitter)
    install(TARGETS DivergenceSplitter RUNTIME DESTINATION .)
else()
    install(TARGETS divergencesplitter_cli RUNTIME DESTINATION .)
endif()
install(TARGETS divergencesplitter_cli RUNTIME DESTINATION .)
install(FILES LICENSE DESTINATION . RENAME LICENSE.txt)
install(FILES DISTRIBUTION-NOTICE.txt DESTINATION .)
install(DIRECTORY licenses/ DESTINATION licenses)

if(WIN32)
    install(CODE "
        file(GLOB _app_dlls \"${CMAKE_BINARY_DIR}/*.dll\")
        list(FILTER _app_dlls EXCLUDE REGEX \"gtest\")
        list(FILTER _app_dlls EXCLUDE REGEX \"Qt6Test\")
        if(_app_dlls)
            file(COPY \${_app_dlls} DESTINATION \"\${CMAKE_INSTALL_PREFIX}\")
        endif()
        foreach(_plugin_dir platforms styles imageformats tls networkinformation generic iconengines platforminputcontexts)
            if(EXISTS \"${CMAKE_BINARY_DIR}/\${_plugin_dir}\")
                file(COPY \"${CMAKE_BINARY_DIR}/\${_plugin_dir}\" DESTINATION \"\${CMAKE_INSTALL_PREFIX}\")
            endif()
        endforeach()
        if(EXISTS \"${CMAKE_BINARY_DIR}/vc_redist.x64.exe\")
            file(COPY \"${CMAKE_BINARY_DIR}/vc_redist.x64.exe\" DESTINATION \"\${CMAKE_INSTALL_PREFIX}\")
        endif()
    ")
endif()

if(WIN32)
    install(CODE "
        file(REMOVE_RECURSE \"\${CMAKE_INSTALL_PREFIX}/include\")
        file(REMOVE_RECURSE \"\${CMAKE_INSTALL_PREFIX}/lib\")
        file(GLOB _test_dlls \"\${CMAKE_INSTALL_PREFIX}/gtest*.dll\")
        if(_test_dlls)
            file(REMOVE \${_test_dlls})
        endif()
    ")
endif()

set(CPACK_GENERATOR "ZIP")
set(CPACK_PACKAGE_NAME "DivergenceSplitter")
set(CPACK_PACKAGE_VENDOR "Nanahuse")
set(CPACK_PACKAGE_VERSION "${PROJECT_VERSION}")
set(CPACK_PACKAGE_FILE_NAME "DivergenceSplitter-${PROJECT_VERSION}-windows-x64")
set(CPACK_INCLUDE_TOPLEVEL_DIRECTORY OFF)
include(CPack)
