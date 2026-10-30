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
option(DIVERGENCESPLITTER_ENABLE_NDI "Build NDI input (requires the official Windows x64 SDK)" OFF)
set(NDI_SDK_DIR "" CACHE PATH "Extracted official NDI SDK root")

if(DIVERGENCESPLITTER_ENABLE_NDI)
    if(NOT WIN32 OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
        message(FATAL_ERROR "NDI integration currently requires Windows x64")
    endif()
    foreach(_header Processing.NDI.Lib.h Processing.NDI.DynamicLoad.h)
        if(NOT EXISTS "${NDI_SDK_DIR}/Include/${_header}")
            message(FATAL_ERROR "NDI SDK missing Include/${_header}; set NDI_SDK_DIR")
        endif()
    endforeach()
    find_file(NDI_RUNTIME_DLL Processing.NDI.Lib.x64.dll
        PATHS "${NDI_SDK_DIR}/Bin/x64" "${NDI_SDK_DIR}/Redist/x64" NO_DEFAULT_PATH REQUIRED NO_CACHE)
    find_file(NDI_RUNTIME_LICENSE Processing.NDI.Lib.Licenses.txt
        PATHS "${NDI_SDK_DIR}/Bin/x64" "${NDI_SDK_DIR}/Redist/x64" "${NDI_SDK_DIR}/Licenses"
              "${NDI_SDK_DIR}" NO_DEFAULT_PATH REQUIRED NO_CACHE)
    set(NDI_SDK_AGREEMENT "${NDI_SDK_DIR}/NDI SDK License Agreement.pdf")
    if(NOT EXISTS "${NDI_SDK_AGREEMENT}")
        message(FATAL_ERROR "NDI SDK license agreement missing from NDI_SDK_DIR")
    endif()
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/tools/ndi-sdk-lock.json" _ndi_lock)
    foreach(_entry runtime runtime_licenses agreement)
        if(_entry STREQUAL "runtime")
            set(_file "${NDI_RUNTIME_DLL}")
        elseif(_entry STREQUAL "runtime_licenses")
            set(_file "${NDI_RUNTIME_LICENSE}")
        else()
            set(_file "${NDI_SDK_AGREEMENT}")
        endif()
        string(JSON _expected GET "${_ndi_lock}" "${_entry}_sha256")
        file(SHA256 "${_file}" _actual)
        if(NOT _actual STREQUAL _expected)
            message(FATAL_ERROR "NDI SDK ${_entry} SHA-256 differs from the reviewed SDK pin")
        endif()
    endforeach()
endif()

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
    src/core/frame_normalizer.cpp
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
    src/capture/camera_devices.cpp
    src/capture/capture_pipeline.cpp
    src/capture/ndi.cpp
    src/capture/ndi_sdk.cpp
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
        tests/camera_tests.cpp
        tests/condition_tests.cpp
        tests/detector_tests.cpp
        tests/frame_cache_tests.cpp
        tests/instance_runtime_tests.cpp
        tests/logging_tests.cpp
        tests/normalizer_tests.cpp
        tests/ndi_tests.cpp
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
    if(DIVERGENCESPLITTER_ENABLE_NDI)
        add_test(NAME ndi_sdk_initialization COMMAND divergencesplitter_cli --ndi-check)
        add_executable(divergencesplitter_ndi_loopback_tests tests/ndi_loopback_tests.cpp)
        target_include_directories(divergencesplitter_ndi_loopback_tests SYSTEM PRIVATE "${NDI_SDK_DIR}/Include")
        target_compile_definitions(divergencesplitter_ndi_loopback_tests PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
        target_link_libraries(divergencesplitter_ndi_loopback_tests PRIVATE divergencesplitter::runtime GTest::gtest_main)
        add_test(NAME ndi_sdk_loopback COMMAND divergencesplitter_ndi_loopback_tests)
        set_tests_properties(ndi_sdk_loopback PROPERTIES TIMEOUT 90 LABELS "ndi;integration")
    endif()

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
        if(DIVERGENCESPLITTER_ENABLE_NDI)
            target_include_directories(divergencesplitter_ui_tests SYSTEM PRIVATE "${NDI_SDK_DIR}/Include")
            target_compile_definitions(divergencesplitter_ui_tests PRIVATE WIN32_LEAN_AND_MEAN NOMINMAX)
        endif()
        add_test(NAME divergencesplitter_ui_tests COMMAND divergencesplitter_ui_tests)
        if(CMAKE_BUILD_TYPE STREQUAL "Debug")
            set(_qt_test_plugin_path "${VCPKG_INSTALLED_DIR}/x64-windows/debug/Qt6/plugins")
        else()
            set(_qt_test_plugin_path "${VCPKG_INSTALLED_DIR}/x64-windows/Qt6/plugins")
        endif()
        set(_ui_test_environment "QT_QPA_PLATFORM=offscreen")
        if(TARGET Qt6::QOffscreenIntegrationPlugin)
            get_target_property(_offscreen_plugin Qt6::QOffscreenIntegrationPlugin IMPORTED_LOCATION_RELEASE)
            if(_offscreen_plugin)
                get_filename_component(_platforms "${_offscreen_plugin}" DIRECTORY)
                get_filename_component(_qt_test_plugin_path "${_platforms}" DIRECTORY)
            endif()
        endif()
        if(EXISTS "${_qt_test_plugin_path}")
            string(APPEND _ui_test_environment ";QT_PLUGIN_PATH=${_qt_test_plugin_path}")
        endif()
        set_tests_properties(divergencesplitter_ui_tests PROPERTIES
            ENVIRONMENT "${_ui_test_environment}"
            TIMEOUT 120
        )
        if(WIN32)
            get_target_property(_qt_core_dll Qt6::Core IMPORTED_LOCATION_RELEASE)
            get_filename_component(_qt_test_bin "${_qt_core_dll}" DIRECTORY)
            set_tests_properties(divergencesplitter_ui_tests PROPERTIES
                ENVIRONMENT_MODIFICATION "PATH=path_list_prepend:${_qt_test_bin}")
        endif()
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
# Third-party license bodies belong to the dependencies, not this repository.
# Collect the actual installed notices only when producing a distribution.
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)
file(TO_CMAKE_PATH "${Python3_EXECUTABLE}" _license_python)
set(_license_qt_args)
if(DIVERGENCESPLITTER_BUILD_UI)
    file(TO_CMAKE_PATH "${Qt6_DIR}" _license_qt_dir)
    set(_license_qt_args "--qt-dir \"${_license_qt_dir}\" --qt-version \"${Qt6_VERSION}\"")
endif()
install(CODE "
    execute_process(
        COMMAND \"${_license_python}\" \"${CMAKE_CURRENT_SOURCE_DIR}/tools/collect_licenses.py\"
            --destination \"\${CMAKE_INSTALL_PREFIX}/licenses\"
            --vcpkg-share \"${VCPKG_INSTALLED_DIR}/${VCPKG_TARGET_TRIPLET}/share\"
            --bridge-source \"${livesplit_bridge_SOURCE_DIR}\"
            --cache \"${CMAKE_BINARY_DIR}/license-cache\"
            ${_license_qt_args}
        COMMAND_ERROR_IS_FATAL ANY
    )
")
if(DIVERGENCESPLITTER_ENABLE_NDI)
    install(FILES "${NDI_RUNTIME_DLL}" "${NDI_RUNTIME_LICENSE}" DESTINATION .)
endif()

if(WIN32)
    install(CODE "
        file(GLOB _app_dlls \"${CMAKE_BINARY_DIR}/*.dll\")
        list(FILTER _app_dlls EXCLUDE REGEX \"gtest\")
        list(FILTER _app_dlls EXCLUDE REGEX \"Qt6Test\")
        list(FILTER _app_dlls EXCLUDE REGEX \"Processing[.]NDI[.]\")
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
