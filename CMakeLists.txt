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

include(cmake/NdiSdk.cmake)

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
find_package(ryml CONFIG REQUIRED)
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

# Discover dependencies here so imported targets and version information are
# available to source, test, and packaging configuration.
if(DIVERGENCESPLITTER_BUILD_UI)
    find_package(Qt6 REQUIRED COMPONENTS Widgets Test)
endif()
if(DIVERGENCESPLITTER_BUILD_TESTS)
    enable_testing()
    find_package(GTest CONFIG REQUIRED)
endif()
find_package(Python3 3.10 REQUIRED COMPONENTS Interpreter)

# Keep executable/DLL deployment paths stable when targets live in subdirectories.
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${PROJECT_BINARY_DIR}")

add_subdirectory(src)
if(DIVERGENCESPLITTER_BUILD_TESTS)
    add_subdirectory(tests)
endif()
include(cmake/Packaging.cmake)
