add_library(divergencesplitter_core STATIC
    src/frame_normalizer.cpp
    src/divergencesplitter/detector/common.hpp
    src/detectors.cpp
    src/conditions.cpp
    src/rules.cpp
    src/scenario_inheritance.cpp
    src/scenario_inheritance.hpp
    src/scenario_yaml.hpp
    src/scenario_loader.cpp
    src/scenario_v2.cpp
    src/text.cpp
    src/value.cpp
    src/yaml_value.cpp
)

add_library(divergencesplitter::core ALIAS divergencesplitter_core)

target_compile_features(divergencesplitter_core PUBLIC cxx_std_23)
target_include_directories(divergencesplitter_core
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
    PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/src"
)
target_link_libraries(divergencesplitter_core
    PUBLIC
        opencv_core
        opencv_imgproc
        opencv_imgcodecs
        ryml::ryml
        nlohmann_json::nlohmann_json
        Threads::Threads
)
