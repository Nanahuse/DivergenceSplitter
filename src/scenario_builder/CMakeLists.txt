if(NOT WIN32)
    message(FATAL_ERROR "DIVERGENCESPLITTER_BUILD_SCENARIO_BUILDER requires Windows")
endif()

set(
    DIVERGENCESPLITTER_WEBVIEW2_VERSION
    "1.0.2903.40"
    CACHE STRING
    "Microsoft.Web.WebView2 NuGet package version"
)
set(
    DIVERGENCESPLITTER_WEBVIEW2_ROOT
    ""
    CACHE PATH
    "Existing WebView2 SDK root (the directory containing build/native)"
)

set(_webview2_arch "x64")
if(CMAKE_SIZEOF_VOID_P EQUAL 4)
    set(_webview2_arch "x86")
endif()

set(_webview2_root "${DIVERGENCESPLITTER_WEBVIEW2_ROOT}")
if(_webview2_root)
    set(_webview2_include "${_webview2_root}/build/native/include")
    set(_webview2_loader "${_webview2_root}/build/native/${_webview2_arch}/WebView2LoaderStatic.lib")
else()
    find_path(_webview2_include
        NAMES WebView2.h
        HINTS ENV WEBVIEW2_SDK_ROOT
        PATH_SUFFIXES build/native/include
    )
    find_library(_webview2_loader
        NAMES WebView2LoaderStatic
        HINTS ENV WEBVIEW2_SDK_ROOT
        PATH_SUFFIXES build/native/${_webview2_arch}
    )
endif()

if(NOT _webview2_include OR NOT _webview2_loader)
    set(_webview2_package
        "${CMAKE_BINARY_DIR}/_deps/webview2/Microsoft.Web.WebView2.${DIVERGENCESPLITTER_WEBVIEW2_VERSION}.nupkg"
    )
    set(_webview2_extract "${CMAKE_BINARY_DIR}/_deps/webview2/sdk")
    if(NOT EXISTS "${_webview2_package}")
        message(STATUS "Downloading Microsoft.Web.WebView2 ${DIVERGENCESPLITTER_WEBVIEW2_VERSION}")
        file(MAKE_DIRECTORY "${CMAKE_BINARY_DIR}/_deps/webview2")
        file(DOWNLOAD
            "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/${DIVERGENCESPLITTER_WEBVIEW2_VERSION}/microsoft.web.webview2.${DIVERGENCESPLITTER_WEBVIEW2_VERSION}.nupkg"
            "${_webview2_package}"
            EXPECTED_HASH SHA256=EF128016DD1E51C59178C827ED5B8AA3322C57AFA8675D930F8109505542AD74
            TLS_VERIFY ON
            SHOW_PROGRESS
            STATUS _webview2_download_status
        )
        list(GET _webview2_download_status 0 _webview2_download_code)
        if(NOT _webview2_download_code EQUAL 0)
            list(GET _webview2_download_status 1 _webview2_download_message)
            message(FATAL_ERROR "Could not download the WebView2 SDK: ${_webview2_download_message}")
        endif()
    endif()
    file(ARCHIVE_EXTRACT
        INPUT "${_webview2_package}"
        DESTINATION "${_webview2_extract}"
    )
    set(_webview2_include "${_webview2_extract}/build/native/include")
    set(_webview2_loader
        "${_webview2_extract}/build/native/${_webview2_arch}/WebView2LoaderStatic.lib"
    )
endif()

if(NOT EXISTS "${_webview2_include}/WebView2.h" OR NOT EXISTS "${_webview2_loader}")
    message(FATAL_ERROR
        "WebView2 SDK was not found. Set DIVERGENCESPLITTER_WEBVIEW2_ROOT to a "
        "Microsoft.Web.WebView2 package directory."
    )
endif()

add_library(divergencesplitter_webview2 UNKNOWN IMPORTED)
set_target_properties(divergencesplitter_webview2 PROPERTIES
    IMPORTED_LOCATION "${_webview2_loader}"
    INTERFACE_INCLUDE_DIRECTORIES "${_webview2_include}"
)

find_program(DIVERGENCESPLITTER_NPM_EXECUTABLE NAMES npm.cmd npm)
if(NOT DIVERGENCESPLITTER_NPM_EXECUTABLE)
    message(FATAL_ERROR "Scenario Builder requires Node.js and npm to build the React frontend")
endif()

set(_scenario_builder_frontend "${PROJECT_SOURCE_DIR}/frontend/scenario-builder")

add_executable(ScenarioBuilder WIN32
    main.cpp
    webview_host.cpp
)
target_compile_features(ScenarioBuilder PRIVATE cxx_std_23)
target_compile_definitions(ScenarioBuilder PRIVATE
    _WIN32_WINNT=0x0A00
    WIN32_LEAN_AND_MEAN
    NOMINMAX
    UNICODE
    _UNICODE
)
target_include_directories(ScenarioBuilder PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(ScenarioBuilder PRIVATE
    divergencesplitter::scenario_editor
    divergencesplitter_webview2
    ole32
    oleaut32
    shell32
    shlwapi
    comdlg32
    comctl32
    user32
    gdi32
    advapi32
    version
)
set_target_properties(ScenarioBuilder PROPERTIES
    WIN32_EXECUTABLE TRUE
    OUTPUT_NAME "ScenarioBuilder"
)

add_custom_target(scenario_builder_frontend
    COMMAND "${DIVERGENCESPLITTER_NPM_EXECUTABLE}" install --no-audit --no-fund
    COMMAND "${DIVERGENCESPLITTER_NPM_EXECUTABLE}" run build
    COMMAND "${CMAKE_COMMAND}" -E copy_directory
        "${_scenario_builder_frontend}/dist"
        "$<TARGET_FILE_DIR:ScenarioBuilder>/scenario-builder-ui"
    WORKING_DIRECTORY "${_scenario_builder_frontend}"
    COMMENT "Building and deploying the Scenario Builder React frontend"
    VERBATIM
)
add_dependencies(ScenarioBuilder scenario_builder_frontend)
